"""Face fingerprinting + speaker-by-face attribution. Feature-52.

Parallel to ``voiceprint_service`` but for visual identity. Process flow:

1. host_agent saves JPEG frames during recording to
   ``workspace/meetings/{id}/frames/{ts_ms}.jpg``.
2. Post-recording, ``process_meeting_recording`` calls
   ``extract_faces_from_meeting(meeting_id)`` which runs mediapipe face
   detection on each frame, crops the dominant face, computes a 128-bit
   perceptual hash, and clusters by hamming distance so frames of the
   same person collapse to one cluster.
3. For each cluster, ``match_centroid`` queries ``faceprints`` (pgvector
   cosine) to see if a known identity registers above threshold.
4. When matched, the alignment step rewrites ``SPEAKER_XX`` labels for
   diarized turns whose midpoint falls within a frame timestamp window
   of the matched cluster.

Quality caveat: imagehash bits are NOT a semantic face embedding; they
encode pixel structure. Cross-meeting matching accuracy is limited
(works best for same-room, same-lighting). A clean upgrade swaps the
``compute_embedding`` body for face_recognition / insightface without
touching callers or the DB schema.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import structlog
from sqlalchemy import delete, select

from app.db.models import FaceprintModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


EMBEDDING_DIM = 128
DEFAULT_MATCH_THRESHOLD = 0.78  # bit-level cosine; tune as quality improves
_CLUSTER_HAMMING_THRESHOLD = 14  # bits-different cap for same-cluster (out of 128)
_CLUSTER_COSINE_THRESHOLD = 0.35  # cosine-distance cap for same-cluster (mesh descriptors)


@dataclass
class FrameDetection:
    frame_path: Path
    ts_ms: int
    face_bbox: Optional[tuple[int, int, int, int]]  # (x, y, w, h) in pixels
    face_crop_path: Optional[Path]
    embedding: Optional[np.ndarray]


@dataclass
class FaceCluster:
    cluster_id: int
    centroid: np.ndarray
    frames: list[FrameDetection] = field(default_factory=list)

    @property
    def ts_range(self) -> tuple[int, int]:
        if not self.frames:
            return (0, 0)
        ts = [f.ts_ms for f in self.frames]
        return (min(ts), max(ts))


def _hash_to_embedding(phash_int: int) -> np.ndarray:
    """Convert a 64-bit phash int into a 128-d float vector.

    We left-pad with zeros to fit the schema's 128-d slot. Cosine
    distance over {0,1} vectors is well-defined; the padding doesn't
    change rank order between matches.
    """
    bits = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for i in range(64):
        if (phash_int >> i) & 1:
            bits[i] = 1.0
    return bits


def _hamming(a: np.ndarray, b: np.ndarray) -> int:
    """Hamming distance over the first 64 bits (the meaningful ones)."""
    return int(np.sum(np.abs(a[:64] - b[:64])))


def _cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (1 - cosine similarity).

    compute_embedding now returns a 128-dim L2-normalized FaceMesh descriptor
    (Feature-56), so cosine — not bit-Hamming — is the right metric. _hamming
    (sum of |a-b| over continuous floats) yields sub-threshold values for every
    pair and collapses all attendees into a single cluster.
    """
    a = a.astype("float32")
    b = b.astype("float32")
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return float(1.0 - float(np.dot(a, b)) / (na * nb))


def _detect_face_bbox(image_path: Path) -> Optional[tuple[int, int, int, int]]:
    """Return (x, y, w, h) of the largest face in the image, or None."""
    try:
        import cv2  # type: ignore[import-not-found]
        import mediapipe as mp  # type: ignore[import-not-found]
    except Exception as e:
        logger.debug("face_detect_deps_missing", error=str(e))
        return None
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    detector = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)
    try:
        result = detector.process(rgb)
    finally:
        detector.close()
    if not result.detections:
        return None
    # Largest by relative bbox area.
    best = max(
        result.detections,
        key=lambda d: d.location_data.relative_bounding_box.width
        * d.location_data.relative_bounding_box.height,
    )
    rel = best.location_data.relative_bounding_box
    x = max(0, int(rel.xmin * w))
    y = max(0, int(rel.ymin * h))
    bw = max(1, int(rel.width * w))
    bh = max(1, int(rel.height * h))
    return (x, y, bw, bh)


def _crop_face(image_path: Path, bbox: tuple[int, int, int, int], out_path: Path) -> bool:
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception:
        return False
    img = cv2.imread(str(image_path))
    if img is None:
        return False
    x, y, w, h = bbox
    crop = img[y:y + h, x:x + w]
    if crop.size == 0:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(out_path), crop))


_FACE_MESH_SINGLETON = None


def _get_face_mesh():
    """Lazy mediapipe FaceMesh singleton — model load is expensive."""
    global _FACE_MESH_SINGLETON
    if _FACE_MESH_SINGLETON is None:
        try:
            import mediapipe as mp
            _FACE_MESH_SINGLETON = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.5,
            )
        except Exception as e:
            logger.debug("face_mesh_init_failed", error=str(e))
            _FACE_MESH_SINGLETON = False
    return _FACE_MESH_SINGLETON or None


# Canonical mediapipe FaceMesh landmark indices for stable geometric pairs.
# Chosen to span eye / nose / mouth / jaw geometry. 64 pairs -> 64 distances.
# Doubled with z-coordinate spread for the second half of the 128-d vector.
_LANDMARK_PAIRS: list[tuple[int, int]] = [
    (33, 263),    # left-eye-outer to right-eye-outer (inter-eye baseline)
    (159, 386),   # eyebrow inner corners
    (133, 362),   # left-eye-inner to right-eye-inner
    (61, 291),    # mouth corners
    (13, 14),     # upper-lip-center to lower-lip-center
    (1, 168),     # nose tip to glabella
    (1, 152),     # nose tip to chin
    (1, 61),      # nose tip to left mouth corner
    (1, 291),     # nose tip to right mouth corner
    (10, 152),    # forehead to chin
    (234, 454),   # cheek-to-cheek width
    (132, 361),   # mid jaw width
    (323, 93),    # outer jaw width
    (152, 10),    # chin to forehead (signed)
    (33, 133),    # left eye width
    (362, 263),   # right eye width
    (159, 145),   # left eye height
    (386, 374),   # right eye height
    (8, 168),     # nasion vertical
    (4, 1),       # nose subnasale to tip
    (197, 152),   # philtrum to chin
    (78, 308),    # mouth inner corners
    (13, 0),      # upper lip to philtrum top
    (17, 18),     # lower lip thickness
    (152, 175),   # chin protrusion
    (10, 67),     # forehead to left temple
    (10, 297),    # forehead to right temple
    (33, 234),    # left eye outer to left cheek
    (263, 454),   # right eye outer to right cheek
    (61, 78),     # left lip outer to inner
    (291, 308),   # right lip outer to inner
    (227, 447),   # widest face width
    (54, 284),    # forehead width
    (143, 372),   # eye-level outer width
    (118, 347),   # nostril-level width
    (50, 280),    # mid-cheek width
    (172, 397),   # mid-jaw width inner
    (136, 365),   # lower jaw width
    (149, 378),   # near-chin width
    (148, 377),   # chin width
    (152, 199),   # chin tip to lower jaw center
    (199, 175),   # lower-jaw vertical
    (175, 152),   # mental protuberance
    (4, 6),       # nose ridge
    (6, 168),     # nose to glabella
    (168, 10),    # glabella to forehead
    (33, 7),      # left eye outer to lower lid corner
    (263, 249),   # right eye outer to lower lid corner
    (133, 155),   # left eye inner to inner lid
    (362, 382),   # right eye inner to inner lid
    (159, 158),   # upper left eyelid spread
    (386, 385),   # upper right eyelid spread
    (145, 144),   # lower left eyelid spread
    (374, 373),   # lower right eyelid spread
    (105, 334),   # eyebrow outer ends
    (52, 282),    # eyebrow inner ends
    (66, 296),    # mid eyebrow span
    (107, 336),   # superior brow span
    (98, 327),    # nostril width
    (49, 279),    # nostril mid width
    (203, 423),   # nasolabial outer width
    (206, 426),   # cheek hollow width
    (216, 436),   # upper jaw width
    (43, 273),    # lateral nasal width
]


def compute_embedding(face_crop_path: Path) -> Optional[np.ndarray]:
    """Compute a 128-dim face embedding for a crop.

    Feature-56: geometry-first descriptor built from mediapipe FaceMesh
    468 landmarks. Sixty-four canonical pairwise distances normalized by
    inter-eye baseline form the first 64 dims; sixty-four z-spread
    distances (depth geometry) fill the second half. L2-normalized to
    keep cosine-distance ordering stable.

    Falls back to imagehash when the mesh fails to detect (occluded,
    extreme angle, low light) so callers always get *something* rather
    than dropping the cluster.
    """
    try:
        from PIL import Image
    except Exception as e:
        logger.debug("face_embedding_deps_missing", error=str(e))
        return None

    try:
        img = Image.open(face_crop_path).convert("RGB")
    except Exception as e:
        logger.debug("face_embedding_open_failed", path=str(face_crop_path), error=str(e))
        return None

    mesh = _get_face_mesh()
    if mesh is not None:
        try:
            arr = np.asarray(img)
            result = mesh.process(arr)
            faces = getattr(result, "multi_face_landmarks", None)
            if faces:
                lm = faces[0].landmark
                # Inter-eye baseline (canonical scale).
                left_eye = np.array([lm[33].x, lm[33].y, lm[33].z], dtype=np.float32)
                right_eye = np.array([lm[263].x, lm[263].y, lm[263].z], dtype=np.float32)
                eye_dist = float(np.linalg.norm(left_eye - right_eye))
                if eye_dist < 1e-6:
                    raise ValueError("degenerate inter-eye distance")

                feats: list[float] = []
                # 64 xy-plane normalized pair distances.
                for a, b in _LANDMARK_PAIRS:
                    pa = np.array([lm[a].x, lm[a].y], dtype=np.float32)
                    pb = np.array([lm[b].x, lm[b].y], dtype=np.float32)
                    feats.append(float(np.linalg.norm(pa - pb) / eye_dist))
                # 64 xyz pair distances — adds depth geometry.
                for a, b in _LANDMARK_PAIRS:
                    pa = np.array([lm[a].x, lm[a].y, lm[a].z], dtype=np.float32)
                    pb = np.array([lm[b].x, lm[b].y, lm[b].z], dtype=np.float32)
                    feats.append(float(np.linalg.norm(pa - pb) / eye_dist))

                vec = np.asarray(feats[:EMBEDDING_DIM], dtype=np.float32)
                if vec.shape[0] < EMBEDDING_DIM:
                    pad = np.zeros(EMBEDDING_DIM - vec.shape[0], dtype=np.float32)
                    vec = np.concatenate([vec, pad])
                norm = float(np.linalg.norm(vec))
                if norm > 1e-6:
                    vec = vec / norm
                return vec.astype("float32")
        except Exception as e:
            logger.debug("face_mesh_embedding_failed", error=str(e))

    # Fallback: imagehash-based descriptor (legacy behaviour).
    try:
        import imagehash
        gray = img.convert("L").resize((128, 128))
        ph = imagehash.phash(gray)
        return _hash_to_embedding(int(str(ph), 16))
    except Exception as e:
        logger.debug("face_embedding_fallback_failed", error=str(e))
        return None


def extract_faces_from_meeting(meeting_id: str, frames_dir: Path) -> list[FaceCluster]:
    """Walk frames_dir, detect + embed each face, cluster by hamming.

    Returns one FaceCluster per distinct person observed. Safe to call
    with a missing or empty frames_dir (returns []).
    """
    if not frames_dir.exists():
        logger.info("face_extract_no_frames_dir", meeting_id=meeting_id, dir=str(frames_dir))
        return []
    frames = sorted(frames_dir.glob("*.jpg"))
    if not frames:
        return []

    crops_dir = frames_dir.parent / "face_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    detections: list[FrameDetection] = []
    t0 = time.perf_counter()
    for frame in frames:
        try:
            ts_ms = int(frame.stem)
        except Exception:
            ts_ms = int(frame.stat().st_mtime * 1000)
        bbox = _detect_face_bbox(frame)
        if bbox is None:
            detections.append(FrameDetection(frame, ts_ms, None, None, None))
            continue
        crop_path = crops_dir / f"{ts_ms}.jpg"
        if not _crop_face(frame, bbox, crop_path):
            detections.append(FrameDetection(frame, ts_ms, bbox, None, None))
            continue
        emb = compute_embedding(crop_path)
        detections.append(FrameDetection(frame, ts_ms, bbox, crop_path, emb))

    # Cluster by cosine distance over the L2-normalized mesh descriptor.
    clusters: list[FaceCluster] = []
    for det in detections:
        if det.embedding is None:
            continue
        assigned = False
        for cluster in clusters:
            if _cosine_dist(det.embedding, cluster.centroid) <= _CLUSTER_COSINE_THRESHOLD:
                cluster.frames.append(det)
                # Update centroid as the mean descriptor of the cluster.
                stack = np.stack([f.embedding for f in cluster.frames if f.embedding is not None])
                cluster.centroid = stack.mean(axis=0).astype("float32")
                assigned = True
                break
        if not assigned:
            clusters.append(FaceCluster(
                cluster_id=len(clusters),
                centroid=det.embedding.copy(),
                frames=[det],
            ))

    elapsed = time.perf_counter() - t0
    logger.info(
        "face_extract_done",
        meeting_id=meeting_id,
        frames=len(frames),
        detections=sum(1 for d in detections if d.embedding is not None),
        clusters=len(clusters),
        elapsed_s=round(elapsed, 2),
    )
    return clusters


class FaceprintService:
    async def enroll(
        self,
        display_name: str,
        embedding: np.ndarray,
        face_crop_path: Optional[str] = None,
        sample_count: int = 1,
        is_primary: bool = False,
        source_meeting_id: Optional[str] = None,
    ) -> tuple[FaceprintModel, bool]:
        if embedding.shape[0] != EMBEDDING_DIM:
            raise ValueError(f"Face embedding dim {embedding.shape[0]} != {EMBEDDING_DIM}")
        async with get_session() as session:
            if is_primary:
                existing_primary = await session.execute(
                    select(FaceprintModel).where(FaceprintModel.is_primary == True)  # noqa: E712
                )
                for row in existing_primary.scalars().all():
                    row.is_primary = False
            existing = await session.execute(
                select(FaceprintModel).where(FaceprintModel.display_name == display_name)
            )
            row = existing.scalar_one_or_none()
            replaced = row is not None
            if row is None:
                row = FaceprintModel(
                    display_name=display_name,
                    embedding=embedding.tolist(),
                    sample_count=int(sample_count),
                    is_primary=is_primary,
                    source_meeting_id=source_meeting_id,
                    face_crop_path=face_crop_path,
                )
                session.add(row)
            else:
                row.embedding = embedding.tolist()
                row.sample_count = int(sample_count)
                if is_primary:
                    row.is_primary = True
                if face_crop_path:
                    row.face_crop_path = face_crop_path
                if source_meeting_id:
                    row.source_meeting_id = source_meeting_id
            await session.flush()
            await session.refresh(row)
            return row, replaced

    async def auto_enroll_from_attendees(
        self,
        attendees: list[str],
        *,
        meeting_id: Optional[str] = None,
    ) -> list[str]:
        """Feature-57 — for each attendee email we don't yet have a face
        for, fetch their Google profile photo via the People API and
        enroll. Returns the list of display_names auto-enrolled (best
        effort — failures are silent so the meeting pipeline still
        finishes).

        Skips primary-user records and any attendee email/name that
        already has a faceprint row.
        """
        if not attendees:
            return []
        import tempfile
        from app.services.google_people_service import get_google_people_service

        people = get_google_people_service()
        async with get_session() as session:
            existing = (await session.execute(
                select(FaceprintModel.display_name)
            )).scalars().all()
        existing_lower = {(n or "").lower() for n in existing}

        enrolled: list[str] = []
        for attendee in attendees:
            if not attendee or "@" not in attendee:
                continue
            display = attendee
            if display.lower() in existing_lower:
                continue
            try:
                photo = await people.fetch_photo(attendee)
            except Exception as exc:  # noqa: BLE001
                logger.debug("auto_enroll_photo_failed", attendee=attendee, error=str(exc))
                continue
            if not photo:
                continue
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(photo)
                tmp_path = Path(tmp.name)
            try:
                embedding = compute_embedding(tmp_path)
                if embedding is None:
                    continue
                await self.enroll(
                    display_name=display,
                    embedding=embedding,
                    face_crop_path=None,
                    sample_count=1,
                    is_primary=False,
                    source_meeting_id=meeting_id,
                )
                enrolled.append(display)
                existing_lower.add(display.lower())
                logger.info("face_auto_enrolled", attendee=attendee, meeting_id=meeting_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("auto_enroll_compute_failed", attendee=attendee, error=str(exc))
            finally:
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
        return enrolled

    async def list_all(self) -> list[FaceprintModel]:
        async with get_session() as session:
            result = await session.execute(
                select(FaceprintModel).order_by(
                    FaceprintModel.is_primary.desc(),
                    FaceprintModel.display_name.asc(),
                )
            )
            return list(result.scalars().all())

    async def delete(self, faceprint_id: int) -> bool:
        async with get_session() as session:
            result = await session.execute(
                delete(FaceprintModel).where(FaceprintModel.id == faceprint_id)
            )
            return (result.rowcount or 0) > 0

    async def match(
        self,
        embedding: np.ndarray,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> Optional[tuple[str, float]]:
        if embedding.shape[0] != EMBEDDING_DIM:
            return None
        async with get_session() as session:
            from sqlalchemy import literal
            stmt = (
                select(
                    FaceprintModel.display_name,
                    FaceprintModel.embedding.cosine_distance(
                        literal(embedding.tolist())
                    ).label("dist"),
                )
                .order_by("dist")
                .limit(1)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                return None
            display_name, dist = row[0], float(row[1])
            similarity = 1.0 - dist
            if similarity < threshold:
                return None
            return display_name, similarity


_instance: Optional[FaceprintService] = None


def get_faceprint_service() -> FaceprintService:
    global _instance
    if _instance is None:
        _instance = FaceprintService()
    return _instance
