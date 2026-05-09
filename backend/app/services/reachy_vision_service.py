"""
Reachy Mini vision service — lazy wrapper over optional vision backends.

Lifted pattern from ``sdk/reachy_mini_toolbox/src/reachy_mini_toolbox/vision/
hand_tracker.py`` (MediaPipe Hands) and the conversation app's YOLOv11n face
detection. This module is deliberately non-strict about dependencies so Zero
can ship without pulling mediapipe/ultralytics into the base image: callers
get a clean ``available: False`` response when the backend is not installed,
and can still see the endpoint exists.

To enable a backend, install:
- ``pip install mediapipe``  → hand tracking via HandTracker
- ``pip install opencv-python`` → face detection via Haar cascade
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import structlog

logger = structlog.get_logger()

DetectorKind = Literal["hands", "face"]


@dataclass
class Detection:
    kind: str          # "hand" | "face"
    x: float           # normalized [0, 1] center x
    y: float           # normalized [0, 1] center y
    width: float       # normalized bbox width
    height: float      # normalized bbox height
    confidence: float  # [0, 1]


class ReachyVisionService:
    _instance: Optional["ReachyVisionService"] = None

    def __init__(self) -> None:
        self._hand_tracker = None
        self._mp_face_detector = None
        self._face_cascade = None

    @classmethod
    def get_instance(cls) -> "ReachyVisionService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Backend availability probes
    # ------------------------------------------------------------------

    def backend_status(self) -> dict:
        mediapipe_face = self._try_import_mediapipe_face()
        opencv = self._try_import_opencv()
        return {
            "hands": self._try_import_mediapipe(),
            "face": {
                "available": bool(mediapipe_face.get("available") or opencv.get("available")),
                "library": "mediapipe+opencv" if mediapipe_face.get("available") and opencv.get("available") else mediapipe_face.get("library") or opencv.get("library"),
                "version": mediapipe_face.get("version") or opencv.get("version"),
                "mediapipe": mediapipe_face,
                "opencv": opencv,
                "reason": None if mediapipe_face.get("available") or opencv.get("available") else opencv.get("reason") or mediapipe_face.get("reason"),
            },
        }

    def _try_import_mediapipe(self) -> dict:
        try:
            import mediapipe  # type: ignore[import-not-found]
            return {"available": True, "library": "mediapipe", "version": getattr(mediapipe, "__version__", "?")}
        except Exception as e:
            return {"available": False, "reason": f"mediapipe not installed: {e}"}

    def _try_import_opencv(self) -> dict:
        try:
            import cv2  # type: ignore[import-not-found]
            return {"available": True, "library": "opencv-python", "version": cv2.__version__}
        except Exception as e:
            return {"available": False, "reason": f"opencv-python not installed: {e}"}

    def _try_import_mediapipe_face(self) -> dict:
        try:
            import mediapipe as mp  # type: ignore[import-not-found]
            _ = mp.solutions.face_detection
            return {"available": True, "library": "mediapipe-face-detection", "version": getattr(mp, "__version__", "?")}
        except Exception as e:
            return {"available": False, "reason": f"mediapipe face detection unavailable: {e}"}

    # ------------------------------------------------------------------
    # Detection entry points
    # ------------------------------------------------------------------

    def detect(self, image_bytes: bytes, *, kind: DetectorKind = "face") -> dict:
        """
        Detect objects in a JPEG / PNG frame. Returns:
            {"available": bool, "detections": [...], "backend": "..."}
        """
        if not image_bytes:
            return {"available": False, "reason": "empty image", "detections": []}
        if kind == "hands":
            return self._detect_hands(image_bytes)
        if kind == "face":
            return self._detect_faces(image_bytes)
        return {"available": False, "reason": f"unknown kind: {kind}", "detections": []}

    async def analyze_latest(self, *, kind: DetectorKind = "face", provider_id: Optional[str] = None) -> dict:
        """
        Pull the latest frame from a SightProvider (defaulting to the active
        one) and run detection. This is the bridge that Phase 4's VLM layer
        will compose with — today it reuses MediaPipe / OpenCV.
        """
        from app.services.sight import get_sight_registry

        reg = get_sight_registry()
        prov = reg.get(provider_id) if provider_id else reg.get_active()
        if prov is None:
            return {
                "available": False,
                "reason": f"no provider named {provider_id!r}" if provider_id else "no active provider",
                "detections": [],
            }
        jpeg = await prov.get_latest_frame()
        if not jpeg:
            return {
                "available": False,
                "reason": f"no frame from provider {prov.name!r}",
                "detections": [],
                "provider": prov.name,
            }
        out = self.detect(jpeg, kind=kind)
        out.setdefault("provider", prov.name)
        return out

    async def analyze_scene(
        self,
        jpeg: Optional[bytes] = None,
        *,
        provider_id: Optional[str] = None,
        kind: DetectorKind = "face",
        question: Optional[str] = None,
    ) -> dict:
        """
        Full scene analysis: VLM caption + MediaPipe/OpenCV detections
        fused into one dict. If `jpeg` is None, pulls from a SightProvider.

        Returns:
            {
              "provider": str | None,
              "caption": str,
              "actionable": str | None,
              "answer": str | None,          # when `question` is given
              "detections": [...],           # face or hand bboxes
              "tags": [...],                 # salient objects
              "available": bool,
            }
        """
        from app.services.sight import get_sight_registry
        from app.services.vision_vlm_service import get_vision_vlm_service

        provider_used: Optional[str] = None
        if jpeg is None:
            reg = get_sight_registry()
            prov = reg.get(provider_id) if provider_id else reg.get_active()
            if prov is None:
                return {
                    "available": False,
                    "reason": "no active sight provider",
                    "caption": "",
                    "detections": [],
                    "tags": [],
                    "actionable": None,
                    "answer": None,
                }
            jpeg = await prov.get_latest_frame()
            provider_used = prov.name
            if not jpeg:
                return {
                    "available": False,
                    "reason": f"no frame from provider {prov.name!r}",
                    "caption": "",
                    "detections": [],
                    "tags": [],
                    "actionable": None,
                    "answer": None,
                    "provider": prov.name,
                }

        vlm = get_vision_vlm_service()
        scene_task = vlm.describe_scene(jpeg)
        answer_task = vlm.answer_about_scene(jpeg, question) if question else None
        scene = await scene_task
        answer = await answer_task if answer_task is not None else None
        detections = self.detect(jpeg, kind=kind)

        return {
            "available": bool(scene.get("caption") or detections.get("detections")),
            "provider": provider_used,
            "model": scene.get("model"),
            "caption": scene.get("caption", ""),
            "actionable": scene.get("actionable"),
            "answer": answer,
            "detections": detections.get("detections", []),
            "backend": detections.get("backend"),
            "tags": [],  # tag_objects is optional + slower; caller can invoke separately
        }

    def _detect_hands(self, image_bytes: bytes) -> dict:
        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np
            # mediapipe 0.10+ hid solutions behind an explicit submodule import.
            # Try the new location first, fall back to the legacy one.
            try:
                from mediapipe.solutions import hands as mp_hands  # type: ignore[import-not-found]
            except Exception:
                import mediapipe as mp  # type: ignore[import-not-found]
                mp_hands = mp.solutions.hands
        except Exception as e:
            return {"available": False, "reason": f"hands backend unavailable: {e}", "detections": []}

        if self._hand_tracker is None:
            self._hand_tracker = mp_hands.Hands(
                static_image_mode=True,
                max_num_hands=2,
                min_detection_confidence=0.5,
            )

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"available": True, "detections": [], "backend": "mediapipe", "error": "decode_failed"}

        h, w = img.shape[:2]
        results = self._hand_tracker.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        detections: list[dict] = []
        for hand_landmarks in results.multi_hand_landmarks or []:
            xs = [lm.x for lm in hand_landmarks.landmark]
            ys = [lm.y for lm in hand_landmarks.landmark]
            detections.append({
                "kind": "hand",
                "x": (min(xs) + max(xs)) / 2,
                "y": (min(ys) + max(ys)) / 2,
                "width": max(xs) - min(xs),
                "height": max(ys) - min(ys),
                "confidence": 1.0,  # MediaPipe doesn't expose bbox confidence directly
            })
        return {
            "available": True,
            "backend": "mediapipe",
            "image_size": {"width": w, "height": h},
            "detections": detections,
        }

    def _detect_faces(self, image_bytes: bytes) -> dict:
        mp_result = self._detect_faces_mediapipe(image_bytes)
        if mp_result.get("detections") or not mp_result.get("fallback_allowed", True):
            return {key: value for key, value in mp_result.items() if key != "fallback_allowed"}

        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np
        except Exception as e:
            return {"available": False, "reason": f"face backend unavailable: {e}", "detections": []}

        if self._face_cascade is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
            if self._face_cascade.empty():
                return {"available": False, "reason": "cascade_load_failed", "detections": []}

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"available": True, "backend": "opencv", "detections": [], "error": "decode_failed"}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        faces = self._face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
        detections = [
            {
                "kind": "face",
                "x": (x + fw / 2) / w,
                "y": (y + fh / 2) / h,
                "width": fw / w,
                "height": fh / h,
                "confidence": 1.0,
            }
            for (x, y, fw, fh) in faces
        ]
        return {
            "available": True,
            "backend": "opencv",
            "fallback_from": mp_result.get("backend") if mp_result.get("available") else None,
            "image_size": {"width": int(w), "height": int(h)},
            "detections": detections,
        }

    def _detect_faces_mediapipe(self, image_bytes: bytes) -> dict:
        try:
            import cv2  # type: ignore[import-not-found]
            import mediapipe as mp  # type: ignore[import-not-found]
            import numpy as np
        except Exception as e:
            return {
                "available": False,
                "reason": f"mediapipe face backend unavailable: {e}",
                "detections": [],
                "fallback_allowed": True,
            }

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {
                "available": True,
                "backend": "mediapipe_face_detection",
                "detections": [],
                "error": "decode_failed",
                "fallback_allowed": False,
            }

        if self._mp_face_detector is None:
            self._mp_face_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1,
                min_detection_confidence=0.35,
            )

        h, w = img.shape[:2]
        results = self._mp_face_detector.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        detections: list[dict] = []
        for det in results.detections or []:
            box = det.location_data.relative_bounding_box
            detections.append({
                "kind": "face",
                "x": max(0.0, min(1.0, float(box.xmin + box.width / 2))),
                "y": max(0.0, min(1.0, float(box.ymin + box.height / 2))),
                "width": max(0.0, min(1.0, float(box.width))),
                "height": max(0.0, min(1.0, float(box.height))),
                "confidence": float(det.score[0]) if det.score else 1.0,
            })
        return {
            "available": True,
            "backend": "mediapipe_face_detection",
            "image_size": {"width": int(w), "height": int(h)},
            "detections": detections,
            "fallback_allowed": True,
        }


def get_reachy_vision_service() -> ReachyVisionService:
    return ReachyVisionService.get_instance()
