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


def compute_embedding(face_crop_path: Path) -> Optional[np.ndarray]:
    """Compute a 128-dim embedding for a face crop. MVP uses imagehash.

    Future: swap to face_recognition.face_encodings (128-d) — exact
    same shape — without changing callers or DB schema.
    """
    try:
        from PIL import Image
        import imagehash
    except Exception as e:
        logger.debug("face_embedding_deps_missing", error=str(e))
        return None
    try:
        img = Image.open(face_crop_path).convert("L").resize((128, 128))
    except Exception as e:
        logger.debug("face_embedding_open_failed", path=str(face_crop_path), error=str(e))
        return None
    ph = imagehash.phash(img)  # 8x8 phash int
    phash_int = int(str(ph), 16)
    return _hash_to_embedding(phash_int)


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

    # Cluster by hamming over the 64-bit phash slice.
    clusters: list[FaceCluster] = []
    for det in detections:
        if det.embedding is None:
            continue
        assigned = False
        for cluster in clusters:
            if _hamming(det.embedding, cluster.centroid) <= _CLUSTER_HAMMING_THRESHOLD:
                cluster.frames.append(det)
                # Update centroid as mean (each dim 0/1 -> float).
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
