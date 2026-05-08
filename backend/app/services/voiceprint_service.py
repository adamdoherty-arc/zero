"""Voice fingerprinting for cross-meeting speaker recognition.

Uses pyannote.audio's wespeaker embedding model (256-dim) to compute a
speaker embedding from a WAV file or a slice of one. Stores the embedding
in the ``voiceprints`` pgvector table so downstream pipelines can match a
diarized cluster's centroid embedding back to a known identity.

Why pyannote/wespeaker-voxceleb-resnet34-LM (256-dim): same embedding space
the diarization 3.1 pipeline uses internally, so the cosine threshold
behavior is consistent. Threshold of ~0.7 is the recommended same-speaker
boundary for this model.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import structlog
from sqlalchemy import select, delete

from app.db.models import VoiceprintModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)

EMBEDDING_DIM = 256
DEFAULT_MATCH_THRESHOLD = 0.70


class VoiceprintService:
    def __init__(self) -> None:
        self._inference = None  # pyannote Inference instance
        self._embedding_model = None

    @property
    def is_loaded(self) -> bool:
        return self._inference is not None

    def load_model(self) -> None:
        """Lazy-load the pyannote embedding model. Requires ZERO_HF_TOKEN."""
        from pyannote.audio import Inference, Model

        settings = get_settings()
        if not settings.hf_token:
            raise ValueError(
                "HuggingFace token (ZERO_HF_TOKEN) required for voice embeddings."
            )
        logger.info("loading_voiceprint_model")
        start = time.perf_counter()
        self._embedding_model = Model.from_pretrained(
            "pyannote/wespeaker-voxceleb-resnet34-LM",
            use_auth_token=settings.hf_token,
        )
        try:
            import torch
            if torch.cuda.is_available():
                self._embedding_model.to(torch.device("cuda"))
        except ImportError:
            pass
        # window="whole" => single embedding for the entire audio segment.
        self._inference = Inference(self._embedding_model, window="whole")
        logger.info(
            "voiceprint_model_loaded",
            elapsed=f"{time.perf_counter() - start:.2f}s",
        )

    def _ensure_loaded(self) -> None:
        if not self.is_loaded:
            self.load_model()

    def compute_embedding(
        self,
        audio_path: Path,
        start_sec: Optional[float] = None,
        end_sec: Optional[float] = None,
    ) -> np.ndarray:
        """Compute a 256-dim speaker embedding for a file or a slice."""
        self._ensure_loaded()
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        from pyannote.core import Segment

        if start_sec is not None and end_sec is not None:
            segment = Segment(float(start_sec), float(end_sec))
            embedding = self._inference.crop(str(audio_path), segment)
        else:
            embedding = self._inference(str(audio_path))

        arr = np.asarray(embedding).astype("float32").reshape(-1)
        if arr.shape[0] != EMBEDDING_DIM:
            raise RuntimeError(
                f"Unexpected embedding dim {arr.shape[0]} (expected {EMBEDDING_DIM})"
            )
        return arr

    def compute_cluster_centroid(
        self,
        audio_path: Path,
        cluster_segments: list[dict],
        max_segments: int = 8,
    ) -> Optional[np.ndarray]:
        """Average embeddings across the longest cluster segments."""
        if not cluster_segments:
            return None
        # Pick the longest segments first (more signal, less likely silence/overlap).
        ranked = sorted(
            cluster_segments,
            key=lambda s: float(s.get("end", 0)) - float(s.get("start", 0)),
            reverse=True,
        )[:max_segments]

        embeddings: list[np.ndarray] = []
        for seg in ranked:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
            if end - start < 0.5:  # skip <500ms slivers
                continue
            try:
                emb = self.compute_embedding(audio_path, start, end)
                embeddings.append(emb)
            except Exception as exc:  # noqa: BLE001
                logger.warning("centroid_segment_failed", error=str(exc), start=start, end=end)
                continue
        if not embeddings:
            return None
        centroid = np.mean(np.stack(embeddings, axis=0), axis=0)
        # Normalize for stable cosine distance.
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid.astype("float32")

    async def enroll(
        self,
        display_name: str,
        embedding: np.ndarray,
        samples_seconds: float,
        is_primary: bool = False,
        source_meeting_id: Optional[str] = None,
    ) -> tuple[VoiceprintModel, bool]:
        """Insert or update a voiceprint by display_name. Returns (model, replaced_existing)."""
        if embedding.shape[0] != EMBEDDING_DIM:
            raise ValueError(f"Embedding dim mismatch: {embedding.shape[0]}")

        async with get_session() as session:
            # If marking primary, demote any existing primary.
            if is_primary:
                existing_primary = await session.execute(
                    select(VoiceprintModel).where(VoiceprintModel.is_primary == True)  # noqa: E712
                )
                for row in existing_primary.scalars().all():
                    row.is_primary = False

            existing = await session.execute(
                select(VoiceprintModel).where(VoiceprintModel.display_name == display_name)
            )
            row = existing.scalar_one_or_none()
            replaced = row is not None
            embedding_list = embedding.tolist()

            if row is None:
                row = VoiceprintModel(
                    display_name=display_name,
                    embedding=embedding_list,
                    samples_seconds=float(samples_seconds),
                    is_primary=is_primary,
                    source_meeting_id=source_meeting_id,
                )
                session.add(row)
            else:
                row.embedding = embedding_list
                row.samples_seconds = float(samples_seconds)
                if is_primary:
                    row.is_primary = True
                if source_meeting_id:
                    row.source_meeting_id = source_meeting_id

            await session.flush()
            await session.refresh(row)
            return row, replaced

    async def list_all(self) -> list[VoiceprintModel]:
        async with get_session() as session:
            result = await session.execute(
                select(VoiceprintModel).order_by(
                    VoiceprintModel.is_primary.desc(),
                    VoiceprintModel.display_name.asc(),
                )
            )
            return list(result.scalars().all())

    async def delete(self, voiceprint_id: int) -> bool:
        async with get_session() as session:
            result = await session.execute(
                delete(VoiceprintModel).where(VoiceprintModel.id == voiceprint_id)
            )
            return (result.rowcount or 0) > 0

    async def match(
        self,
        embedding: np.ndarray,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> Optional[tuple[str, float]]:
        """Find the best-matching voiceprint by cosine similarity. Returns
        (display_name, similarity) when above threshold, else None."""
        if embedding.shape[0] != EMBEDDING_DIM:
            return None

        async with get_session() as session:
            # pgvector's <=> is cosine distance (1 - cosine_similarity).
            from sqlalchemy import literal

            stmt = (
                select(
                    VoiceprintModel.display_name,
                    VoiceprintModel.embedding.cosine_distance(literal(embedding.tolist())).label("dist"),
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


_instance: VoiceprintService | None = None


def get_voiceprint_service() -> VoiceprintService:
    global _instance
    if _instance is None:
        _instance = VoiceprintService()
    return _instance
