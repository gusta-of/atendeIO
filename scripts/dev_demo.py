#!/usr/bin/env python3
"""Servidor de DEMONSTRAÇÃO: detector falso + vídeo sintético, sem webcam nem YOLO.

    python scripts/dev_demo.py [--port 8001]

Cria o utilizador demo/demo-senha-123 e uma câmera local com um vídeo gerado (uma "pessoa" que anda).
Serve para ver e testar a interface sem hardware. Dados em /tmp/atendeio-demo (descartáveis)."""

import argparse
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendeio.api.app import create_app  # noqa: E402
from atendeio.config import Settings  # noqa: E402
from atendeio.container import build_container  # noqa: E402


class WalkingDetector:
    """Uma 'pessoa' que anda de um lado a outro, para as áreas e contadores terem o que mostrar."""
    def __init__(self):
        self.t = 0

    def load(self):
        return None

    def detect(self, frame, classes=None, masks=False):
        if classes is not None and not len(classes):
            return []
        self.t += 1
        cx = 0.5 + 0.35 * np.sin(self.t / 25)
        cy = 0.55
        out = [{"name": "person", "cls": 0, "conf": 0.9, "cx": cx, "cy": cy, "box": (cx - 0.07, cy - 0.2, cx + 0.07, cy + 0.2)}]
        return [d for d in out if classes is None or d["cls"] in classes]


def make_video(path: Path) -> None:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 15, (640, 360))
    for i in range(450):
        img = np.full((360, 640, 3), (40, 34, 28), np.uint8)
        cv2.rectangle(img, (60, 220), (220, 330), (70, 90, 60), -1)
        cv2.rectangle(img, (400, 200), (580, 320), (60, 70, 100), -1)
        cv2.putText(img, f"demo {i:03d}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
        w.write(img)
    w.release()


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--cors", default="", help="origens de apps nativos, separadas por vírgula (ex.: capacitor://localhost,https://localhost)")
    args = ap.parse_args()
    data = Path(tempfile.gettempdir()) / "atendeio-demo"
    data.mkdir(exist_ok=True)
    video = data / "demo.avi"
    if not video.exists():
        make_video(video)
    settings = Settings(data_dir=data, port=args.port, host="127.0.0.1", allow_signup=True,
                        cors_origins=tuple(o.strip().rstrip("/") for o in args.cors.split(",") if o.strip()))
    container = build_container(settings, device_lister=lambda: [{"ref": str(video), "name": "Câmera demo"}],
                                detector=WalkingDetector())
    try:
        container.auth.create_user("demo", "demo-senha-123")
    except Exception:
        pass
    print(f"[demo] http://127.0.0.1:{args.port}/app/   usuário: demo   senha: demo-senha-123")
    uvicorn.run(create_app(container=container), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
