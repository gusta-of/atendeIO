"""YOLO: carga dos modelos e inferência serializada (não desenha: ver vision/draw.py e areas_draw.py).

Dois modelos da mesma família: o de detecção (leve, usado sempre) e o de segmentação (devolve também a
silhueta de cada objeto; só entra quando as áreas precisam ficar "atrás" de quem está na frente)."""

import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

POLY_MAX_POINTS = 40


class Detector:
    """Os modelos não são thread-safe: `detect` serializa as inferências (CPU é o recurso caro)."""

    def __init__(self, model_path: Path, conf: float, seg_path: Optional[Path] = None):
        self._model_path, self._seg_path, self._conf = model_path, seg_path, conf
        self._model = None
        self._seg = None
        self._seg_failed = False
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()

    def load(self):
        with self._load_lock:
            if self._model is None:
                from ultralytics import YOLO  # import pesado: só quando precisa
                print(f"[*] Carregando {self._model_path} ...")
                model = YOLO(str(self._model_path))
                model(np.zeros((480, 640, 3), np.uint8), verbose=False)  # aquece
                from .classes import _ordered_names
                if [model.names[i] for i in range(len(model.names))] != _ordered_names():
                    print("[!] O modelo tem classes diferentes do catálogo COCO: atualize vision/classes.py")
                self._model = model
                print("[+] Modelo pronto.")
            return self._model

    def _load_seg(self):
        """Modelo de segmentação sob demanda. Se não carregar (sem rede para baixar, arquivo ruim),
        avisa UMA vez e devolve None: as áreas seguem sem oclusão, a câmera não cai."""
        with self._load_lock:
            if self._seg is None and not self._seg_failed and self._seg_path is not None:
                try:
                    from ultralytics import YOLO
                    print(f"[*] Carregando {self._seg_path} (silhuetas; baixa sozinho na 1ª vez) ...")
                    seg = YOLO(str(self._seg_path))
                    seg(np.zeros((480, 640, 3), np.uint8), verbose=False)
                    self._seg = seg
                    print("[+] Modelo de segmentação pronto.")
                except Exception as e:
                    self._seg_failed = True
                    print(f"[!] Sem segmentação ({type(e).__name__}): as áreas ficarão por cima de quem está na frente.")
            return self._seg

    @staticmethod
    def _polys(result, i: int, w: int, h: int):
        """Contorno normalizado (≤ POLY_MAX_POINTS) da silhueta `i`, ou None."""
        try:
            xy = result.masks.xy[i]
        except (AttributeError, IndexError, TypeError):
            return None
        if xy is None or len(xy) < 3:
            return None
        pts = np.asarray(xy, np.float32).reshape(-1, 1, 2)
        eps = 1.0
        approx = cv2.approxPolyDP(pts, eps, True)
        while len(approx) > POLY_MAX_POINTS and eps < 20:  # simplifica mais até caber no limite
            eps *= 1.6
            approx = cv2.approxPolyDP(pts, eps, True)
        return [(float(x) / w, float(y) / h) for x, y in approx.reshape(-1, 2)] if len(approx) >= 3 else None

    def detect(self, frame: np.ndarray, classes=None, masks: bool = False) -> list:
        """Roda o YOLO e devolve, sem mexer no frame,
        [{"name","cls","conf","cx","cy","box"[, "poly"]}] com centro e box (x1,y1,x2,y2) normalizados (0..1).

        `classes`: ids a reconhecer (None = todas as 80). Lista vazia = não reconhece nada e NEM roda
        o modelo (a CPU é o recurso caro).
        `masks`: pede também a silhueta (`poly`) de cada detecção; usa o modelo de segmentação, se houver."""
        if classes is not None and not len(classes):
            return []
        model = self.load()
        seg = self._load_seg() if masks else None
        kwargs = {} if classes is None else {"classes": sorted(classes)}
        with self._infer_lock:
            results = (seg or model)(frame, conf=self._conf, verbose=False, **kwargs)
        r = results[0]
        h, w = frame.shape[:2]
        names = (seg or model).names
        dets = []
        for i, box in enumerate(r.boxes):
            cls_id, c = int(box.cls[0]), float(box.conf[0])
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            d = {"name": names[cls_id], "cls": cls_id, "conf": c,
                 "cx": (x1 + x2) / 2 / w, "cy": (y1 + y2) / 2 / h,
                 "box": (x1 / w, y1 / h, x2 / w, y2 / h)}
            if seg is not None:
                poly = self._polys(r, i, w, h)
                if poly:
                    d["poly"] = poly
            dets.append(d)
        return dets
