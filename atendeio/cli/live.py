"""Live view local em janela OpenCV (debug de câmera/modelo, sem o painel web).

    python -m atendeio.cli.live --list
    python -m atendeio.cli.live --source /dev/video0
    python -m atendeio.cli.live --source rtsp://user:senha@192.168.1.50:554/stream1

Tecla na janela: q — sair
"""

import argparse
import time

import cv2

from ..config import Settings
from ..vision.detector import Detector
from ..vision.inventory import summarize
from ..vision.sources import list_v4l2_devices, open_source


def _describe(dets: list) -> str:
    inv = summarize(dets)
    return ", ".join(f"{c['count']} {c['name']}" for c in inv["counts"]) or "nada detectado"


def run(source, detector: Detector, window: str = "atendeIO live") -> None:
    cap, fps = open_source(source), 0.0
    print("[*] Live view rodando — q sai.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("[-] Perdi o frame da câmera. Reabrindo...")
                time.sleep(1)
                cap.release()
                cap = open_source(source)
                continue
            t0 = time.time()
            dets = detector.detect(frame)
            dt = max(time.time() - t0, 1e-4)
            fps = 0.9 * fps + 0.1 / dt if fps else 1.0 / dt
            cv2.putText(frame, f"{_describe(dets)}  fps: {fps:.1f}", (10, frame.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(window, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconhecimento de ambiente live (YOLOv8n)")
    ap.add_argument("--list", action="store_true", help="lista as câmeras locais e sai")
    ap.add_argument("--source", help="índice, /dev/videoN ou rtsp:// (padrão: 1ª câmera local)")
    cfg = Settings.from_env()
    ap.add_argument("--conf", type=float, default=cfg.conf_threshold, help="confiança mínima")
    args = ap.parse_args()

    devices = list_v4l2_devices()
    if args.list:
        for d in devices:
            print(f"{d['ref']}  ({d['name']})")
        return
    source = args.source or (devices[0]["ref"] if devices else None)
    if source is None:
        raise SystemExit("Nenhuma câmera encontrada. Use --source.")
    if str(source).isdigit():
        source = int(source)
    run(source, Detector(cfg.model_path, args.conf))


if __name__ == "__main__":
    main()
