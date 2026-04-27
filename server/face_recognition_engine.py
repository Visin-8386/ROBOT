"""
Face recognition engine using InsightFace (ArcFace + SCRFD via ONNX):
1) Detect face inside a person crop (SCRFD)
2) Generate face embedding (ArcFace / buffalo_l)
3) Compare with known embeddings (cosine similarity)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import os
import site

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EMBEDDING_DB_PATH = BASE_DIR / "known_faces" / "embeddings.npz"


def _setup_windows_cuda_dll_paths() -> List[str]:
    """Ensure CUDA/cuDNN DLL directories from pip packages are visible on Windows."""
    if os.name != "nt":
        return []

    candidates = []
    try:
        candidates.append(Path(site.getusersitepackages()))
    except Exception:
        pass

    try:
        for p in site.getsitepackages():
            candidates.append(Path(p))
    except Exception:
        pass

    seen = set()
    added_paths: List[str] = []
    for base in candidates:
        if not base.exists():
            continue
        for rel in [
            Path("nvidia") / "cudnn" / "bin",
            Path("nvidia") / "cublas" / "bin",
            Path("nvidia") / "cuda_runtime" / "bin",
            Path("nvidia") / "cuda_nvrtc" / "bin",
            Path("nvidia") / "cufft" / "bin",
            Path("onnxruntime") / "capi",
        ]:
            dll_dir = (base / rel).resolve()
            key = str(dll_dir).lower()
            if dll_dir.exists() and key not in seen:
                seen.add(key)
                try:
                    os.add_dll_directory(str(dll_dir))
                    added_paths.append(str(dll_dir))
                except Exception:
                    pass
    return added_paths


_CUDA_DLL_DIRS = _setup_windows_cuda_dll_paths()

# Import ONNX/InsightFace only after DLL directories are registered.
import onnxruntime as ort
import insightface


@dataclass
class FaceMatch:
    name: str
    similarity: float
    is_known: bool
    face_bbox_global: Tuple[int, int, int, int]


class FaceRecognitionEngine:
    def __init__(
        self,
        embedding_db_path: str = str(DEFAULT_EMBEDDING_DB_PATH),
        similarity_threshold: float = 0.50, # Threshold for ArcFace (0.45 - 0.55 is good)
        device: Optional[str] = None,
        det_size: int = 320,
        max_crop_side: int = 320,
    ):
        # Reinforce DLL lookup for child libraries (some ORT loads rely on PATH lookup).
        if os.name == "nt" and _CUDA_DLL_DIRS:
            cur_path = os.environ.get("PATH", "")
            for p in _CUDA_DLL_DIRS:
                if p.lower() not in cur_path.lower():
                    cur_path = p + os.pathsep + cur_path
            os.environ["PATH"] = cur_path

        self.device_str = device if device else "gpu" # Prefer GPU when available
        self.similarity_threshold = similarity_threshold
        self.embedding_db_path = Path(embedding_db_path)
        self.det_size = max(160, int(det_size))
        self.max_crop_side = max(128, int(max_crop_side))

        available = ort.get_available_providers()
        want_gpu = self.device_str != "cpu"

        print(f"[FaceID] Init InsightFace 'buffalo_l' (ArcFace) ...")
        self.app = None
        self.device = "CPU/ONNX"

        # Try CUDA first when available, but gracefully fall back to CPU if CUDA EP cannot load.
        if want_gpu and "CUDAExecutionProvider" in available:
            try:
                self.app = insightface.app.FaceAnalysis(
                    name='buffalo_l',
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                self.app.prepare(ctx_id=0, det_size=(self.det_size, self.det_size))
                self.device = "CUDA/ONNX"
            except Exception as e:
                print(f"[FaceID] CUDA provider unavailable at runtime, fallback CPU: {e}")

        if self.app is None:
            self.app = insightface.app.FaceAnalysis(
                name='buffalo_l',
                providers=["CPUExecutionProvider"],
            )
            self.app.prepare(ctx_id=-1, det_size=(self.det_size, self.det_size))
            self.device = "CPU/ONNX"

        self.known_names: List[str] = []
        self.known_embeddings: Optional[np.ndarray] = None
        self.load_embeddings()

    def load_embeddings(self) -> None:
        """Load saved embeddings from .npz file if available."""
        if not self.embedding_db_path.exists():
            self.known_names = []
            self.known_embeddings = None
            print(f"[FaceID] Database not found: {self.embedding_db_path}")
            return

        data = np.load(self.embedding_db_path, allow_pickle=True)
        names = data["names"].tolist()
        embeddings = data["embeddings"].astype(np.float32)

        # Normalize existing embeddings perfectly via numpy
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.where(norms == 0, 1e-10, norms)

        self.known_names = [str(x) for x in names]
        self.known_embeddings = embeddings
        print(f"[FaceID] Loaded {len(self.known_names)} identities.")

    def _extract_and_embed(
        self,
        frame_bgr: np.ndarray,
        person_bbox: Tuple[int, int, int, int],
    ) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int, int, int]]]:
        """
        Detect face inside person bounding box and return its embedding + bbox.
        """
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = person_bbox
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w-1, x2), min(h-1, y2)

        if x2 <= x1 or y2 <= y1:
            return None, None

        person_crop_bgr = frame_bgr[y1:y2, x1:x2]
        if person_crop_bgr.size == 0:
            return None, None

        # Reduce detector workload on large person crops while preserving bbox mapping.
        crop_h, crop_w = person_crop_bgr.shape[:2]
        scale = 1.0
        longest = max(crop_h, crop_w)
        if longest > self.max_crop_side:
            scale = self.max_crop_side / float(longest)
            new_w = max(1, int(crop_w * scale))
            new_h = max(1, int(crop_h * scale))
            person_crop_bgr = cv2.resize(person_crop_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # InsightFace processes BGR directly
        faces = self.app.get(person_crop_bgr)
        if not faces:
            return None, None

        # Get largest face if multiple detected
        best_face = None
        best_area = 0.0
        for face in faces:
            fx1, fy1, fx2, fy2 = face.bbox
            area = max(0.0, (fx2 - fx1) * (fy2 - fy1))
            if area > best_area:
                best_area = area
                best_face = face

        if best_face is None:
            return None, None

        fx1, fy1, fx2, fy2 = map(float, best_face.bbox)
        if scale != 1.0:
            inv = 1.0 / scale
            fx1, fy1, fx2, fy2 = fx1 * inv, fy1 * inv, fx2 * inv, fy2 * inv

        fx1, fy1, fx2, fy2 = map(int, (fx1, fy1, fx2, fy2))
        face_bbox_global = (x1 + fx1, y1 + fy1, x1 + fx2, y1 + fy2)

        emb = best_face.normed_embedding
        return emb, face_bbox_global

    def match_person_face(
        self,
        frame_bgr: np.ndarray,
        person_bbox: Tuple[int, int, int, int],
    ) -> Optional[FaceMatch]:
        """
        Run InsightFace for one person bbox and return identity result.
        """
        query_emb, face_bbox_global = self._extract_and_embed(frame_bgr, person_bbox)
        
        if query_emb is None or face_bbox_global is None:
            return None

        if self.known_embeddings is None or len(self.known_names) == 0:
            return FaceMatch(
                name="UNKNOWN",
                similarity=0.0,
                is_known=False,
                face_bbox_global=face_bbox_global,
            )

        # Cosine similarity using Dot Product (since both are L2 normalized)
        similarities = np.dot(self.known_embeddings, query_emb)
        best_idx = np.argmax(similarities)
        score = float(similarities[best_idx])
        
        name = self.known_names[best_idx] if score >= self.similarity_threshold else "UNKNOWN"

        return FaceMatch(
            name=name,
            similarity=score,
            is_known=name != "UNKNOWN",
            face_bbox_global=face_bbox_global,
        )

    def match_all_persons(
        self,
        frame_bgr: np.ndarray,
        person_detections: List[Dict],
    ) -> Dict[int, FaceMatch]:
        """
        Match faces for all detected persons.
        Returns map: track_id -> FaceMatch
        """
        results: Dict[int, FaceMatch] = {}
        for det in person_detections:
            bbox = det.get("bbox")
            track_id = int(det.get("id", -1))
            if not bbox:
                continue

            match = self.match_person_face(frame_bgr, bbox)
            if match is not None:
                results[track_id] = match

        return results
