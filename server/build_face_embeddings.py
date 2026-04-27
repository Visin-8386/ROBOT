"""
Build known face embeddings database from folder structure using InsightFace (ArcFace).

known_faces/
  alice/
    1.jpg
    2.jpg
  bob/
    a.png

Output: known_faces/embeddings.npz
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import cv2
import numpy as np
import insightface

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FACES_DIR = BASE_DIR / "known_faces"
DEFAULT_EMBEDDINGS_PATH = DEFAULT_FACES_DIR / "embeddings.npz"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ArcFace embeddings database using InsightFace")
    parser.add_argument("--faces-dir", default=str(DEFAULT_FACES_DIR), help="Directory containing person subfolders")
    parser.add_argument("--output", default=str(DEFAULT_EMBEDDINGS_PATH), help="Output .npz file path")
    return parser.parse_args()


def build_embeddings(faces_dir: str, output: str) -> int:
    """Build embeddings from face images and return number of identities."""
    faces_dir_path = Path(faces_dir)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not faces_dir_path.exists():
        raise FileNotFoundError(f"Faces directory not found: {faces_dir_path}")

    # Initialize InsightFace
    print("[FaceDB] Initializing InsightFace model...")
    app = insightface.app.FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    # Fast ctx_id assignment logic
    try:
        app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception:
        app.prepare(ctx_id=-1, det_size=(640, 640))

    names: List[str] = []
    embeddings: List[np.ndarray] = []

    person_dirs = [d for d in faces_dir_path.iterdir() if d.is_dir()]
    person_dirs.sort(key=lambda x: x.name)

    for person_dir in person_dirs:
        person_name = person_dir.name
        image_paths = [
            p for p in person_dir.glob("**/*")
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
        ]

        if not image_paths:
            continue

        person_embs: List[np.ndarray] = []
        for img_path in image_paths:
            bgr = cv2.imread(str(img_path))
            if bgr is None:
                continue

            faces = app.get(bgr)
            if not faces:
                print(f"[Warning] No face found in {img_path}")
                continue

            # Pick largest
            best_face = None
            best_area = 0.0
            for face in faces:
                fx1, fy1, fx2, fy2 = face.bbox
                area = max(0.0, (fx2 - fx1) * (fy2 - fy1))
                if area > best_area:
                    best_area = area
                    best_face = face

            if best_face is None:
                continue

            emb = best_face.normed_embedding
            person_embs.append(emb)

        if not person_embs:
            print(f"[FaceDB] {person_name}: no valid faces")
            continue

        # Average embeddings for better representation
        mean_emb = np.mean(np.stack(person_embs, axis=0), axis=0)
        norm = np.linalg.norm(mean_emb)
        if norm > 0:
            mean_emb = mean_emb / norm

        names.append(person_name)
        embeddings.append(mean_emb.astype(np.float32))
        print(f"[FaceDB] {person_name}: Processed {len(person_embs)} valid face samples")

    if not embeddings:
        raise RuntimeError("No embeddings were built. Check your training images.")

    emb_array = np.stack(embeddings, axis=0).astype(np.float32)
    np.savez(output_path, names=np.array(names, dtype=object), embeddings=emb_array)
    print(f"[FaceDB] Successfully exported {len(names)} identities to {output_path}")
    return len(names)


def main() -> None:
    args = parse_args()
    build_embeddings(args.faces_dir, args.output)

if __name__ == "__main__":
    main()
