"""
Webcam test pipeline:
YOLO person detect -> crop person box -> face detect/embedding -> match known embeddings.

Run:
  python webcam_face_reid_test.py --camera 0 --embeddings known_faces/embeddings.npz
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Dict, Tuple

import cv2

from build_face_embeddings import build_embeddings
from detector import PersonDetector
from face_recognition_engine import FaceRecognitionEngine
from face_recognition_engine import FaceMatch

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FACES_DIR = BASE_DIR / "known_faces"
DEFAULT_EMBEDDINGS_PATH = DEFAULT_FACES_DIR / "embeddings.npz"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Webcam person+face re-identification test")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index")
    parser.add_argument("--embeddings", default=str(DEFAULT_EMBEDDINGS_PATH), help="Path to embeddings .npz")
    parser.add_argument("--faces-dir", default=str(DEFAULT_FACES_DIR), help="Directory containing known face images")
    parser.add_argument("--threshold", type=float, default=0.65, help="Similarity threshold for known/unknown")
    parser.add_argument("--skip", type=int, default=1, help="Run detector every N frames to reduce load")
    parser.add_argument("--face-interval", type=int, default=3, help="Run face matching every N detector cycles")
    parser.add_argument("--max-face-persons", type=int, default=2, help="Maximum number of person boxes to run face matching per cycle")
    parser.add_argument("--cache-ttl", type=float, default=2.0, help="Seconds to reuse face match result per track ID")
    parser.add_argument("--print-interval", type=float, default=1.0, help="Seconds between terminal metric prints")
    parser.add_argument("--auto-build", dest="auto_build", action="store_true", help="Auto build/rebuild embeddings when needed")
    parser.add_argument("--no-auto-build", dest="auto_build", action="store_false", help="Disable auto build/rebuild")
    parser.set_defaults(auto_build=True)
    return parser.parse_args()


def latest_image_mtime(faces_dir: Path) -> float:
    latest = 0.0
    for p in faces_dir.glob("**/*"):
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
            mtime = p.stat().st_mtime
            if mtime > latest:
                latest = mtime
    return latest


def main() -> None:
    args = parse_args()

    faces_dir = Path(args.faces_dir).resolve()
    emb_path = Path(args.embeddings).resolve()

    if args.auto_build:
        if not faces_dir.exists():
            print(f"[FaceDB] Skip auto build: {faces_dir} not found")
        else:
            need_build = False
            if not emb_path.exists():
                need_build = True
            else:
                latest_face_ts = latest_image_mtime(faces_dir)
                if latest_face_ts > emb_path.stat().st_mtime:
                    need_build = True

            if need_build:
                print("[FaceDB] Building embeddings from known_faces...")
                try:
                    count = build_embeddings(str(faces_dir), str(emb_path))
                    print(f"[FaceDB] Ready with {count} identities")
                except Exception as exc:
                    print(f"[FaceDB] Auto build failed: {exc}")

    print("[Init] Loading YOLO person detector...")
    detector = PersonDetector(enable_preprocess=False)

    print("[Init] Loading face recognition engine...")
    face_engine = FaceRecognitionEngine(
        embedding_db_path=str(emb_path),
        similarity_threshold=args.threshold,
    )

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open webcam index {args.camera}")

    print("[Run] Press q to quit")

    frame_idx = 0
    infer_cycle_idx = 0
    detections = []
    face_matches: Dict[int, FaceMatch] = {}
    face_cache: Dict[int, Tuple[FaceMatch, float]] = {}
    fps_t0 = time.time()
    fps_count = 0
    view_fps = 0.0
    print_t0 = time.time()
    last_yolo_ms = 0.0
    last_face_ms = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            frame_idx += 1
            do_infer = (frame_idx % max(1, args.skip)) == 0

            if do_infer:
                infer_cycle_idx += 1
                infer_t0 = time.time()
                detections, _ = detector.detect_confirmed(frame, target_type="person")
                infer_t1 = time.time()
                # Keep only largest persons first to cap FaceReID cost.
                sorted_dets = sorted(detections, key=lambda d: d.get("area", 0), reverse=True)
                candidates = sorted_dets[: max(0, args.max_face_persons)]

                # Refresh stale cache entries and keep active IDs only.
                now_ts = time.time()
                active_ids = {int(d.get("id", -1)) for d in detections}
                for stale_id in [k for k in face_cache.keys() if (now_ts - face_cache[k][1]) > args.cache_ttl or k not in active_ids]:
                    del face_cache[stale_id]

                should_run_face = (infer_cycle_idx % max(1, args.face_interval)) == 0
                if should_run_face:
                    # Only run FaceReID on IDs not fresh in cache.
                    to_match = []
                    for det in candidates:
                        det_id = int(det.get("id", -1))
                        cached = face_cache.get(det_id)
                        if cached is None or (now_ts - cached[1]) > args.cache_ttl:
                            to_match.append(det)

                    if to_match:
                        new_matches = face_engine.match_all_persons(frame, to_match)
                        now_ts = time.time()
                        for mid, mval in new_matches.items():
                            face_cache[mid] = (mval, now_ts)

                # Build face_matches from current cache for all visible detections.
                face_matches = {}
                for det in detections:
                    det_id = int(det.get("id", -1))
                    cached = face_cache.get(det_id)
                    if cached is not None:
                        face_matches[det_id] = cached[0]
                infer_t2 = time.time()
                last_yolo_ms = (infer_t1 - infer_t0) * 1000.0
                last_face_ms = (infer_t2 - infer_t1) * 1000.0

            for det in detections:
                x1, y1, x2, y2 = det["bbox"]
                track_id = int(det.get("id", -1))

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 255), 2)
                cv2.putText(
                    frame,
                    f"Person ID:{track_id}",
                    (x1, max(20, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 220, 255),
                    2,
                )

                if track_id in face_matches:
                    match = face_matches[track_id]
                    fx1, fy1, fx2, fy2 = match.face_bbox_global
                    color = (0, 255, 0) if match.is_known else (0, 0, 255)
                    label = f"{match.name} ({match.similarity:.2f})"

                    cv2.rectangle(frame, (fx1, fy1), (fx2, fy2), color, 2)
                    cv2.putText(
                        frame,
                        label,
                        (fx1, max(20, fy1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        2,
                    )

            fps_count += 1
            elapsed = time.time() - fps_t0
            if elapsed >= 1.0:
                view_fps = fps_count / elapsed
                fps_count = 0
                fps_t0 = time.time()

            cv2.putText(
                frame,
                f"FPS:{view_fps:.1f} | People:{len(detections)} | KnownDB:{len(face_engine.known_names)} | Y:{last_yolo_ms:.1f}ms F:{last_face_ms:.1f}ms",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
            )

            if args.print_interval > 0 and (time.time() - print_t0) >= args.print_interval:
                known_count = sum(1 for m in face_matches.values() if m.is_known)
                unknown_count = len(face_matches) - known_count
                print(
                    f"[Metrics] FPS:{view_fps:.1f} | People:{len(detections)} | "
                    f"FaceMatched:{len(face_matches)} (Known:{known_count}, Unknown:{unknown_count}) | "
                    f"YOLO:{last_yolo_ms:.1f}ms | FaceReID:{last_face_ms:.1f}ms | "
                    f"KnownDB:{len(face_engine.known_names)}"
                )
                print_t0 = time.time()

            cv2.imshow("Webcam Face ReID Test", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
