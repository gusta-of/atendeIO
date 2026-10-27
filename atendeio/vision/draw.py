"""Desenho das caixas do YOLO (só pra quem pede: o vídeo limpo não passa por aqui)."""

import cv2
import numpy as np


def _color_for(cls_id: int):
    """Cor estável por classe (HSV espalhado pelo círculo)."""
    bgr = cv2.cvtColor(np.uint8([[[(cls_id * 47) % 180, 200, 230]]]), cv2.COLOR_HSV2BGR)[0][0]
    return tuple(int(v) for v in bgr)


def draw_detections(frame: np.ndarray, dets: list) -> None:
    """Desenha, no próprio frame, as caixas das detecções (box normalizado 0..1)."""
    h, w = frame.shape[:2]
    for d in dets:
        x1, y1, x2, y2 = int(d["box"][0] * w), int(d["box"][1] * h), int(d["box"][2] * w), int(d["box"][3] * h)
        color = _color_for(d["cls"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
        label = f"{d['name']} {d['conf']:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = y1 - 4 if y1 - th - 6 > 0 else y1 + th + 4  # rótulo dentro do quadro se a caixa encosta no topo
        cv2.rectangle(frame, (x1, ty - th - 3), (x1 + tw + 4, ty + 3), color, -1)
        cv2.putText(frame, label, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
