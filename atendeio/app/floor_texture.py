"""Piso do mapa "simulado" a partir das imagens das câmeras (sem Qt).

Com o chão calibrado, a imagem da câmera é deformada (homografia) para a vista de CIMA, ocupando a zona da câmera no mapa. Vários
quadros ao longo do tempo viram uma MEDIANA por pixel, o que apaga quem passou (pessoas andando somem; o que fica parado, como o
chão, a mesa e o tapete, permanece). Só vive na memória: nada disso é gravado em disco nem sai do computador."""

from typing import List, Optional

import cv2
import numpy as np

from .floor_calib import FloorCalib

TEX_W = 640             # largura da textura da zona (a altura segue a proporção da câmera)
MIN_SAMPLES = 3         # com menos quadros que isto a mediana ainda não apaga as pessoas
KEEP = 7                # quadros guardados por câmera


def tex_size(aspect: float, width: int = TEX_W) -> tuple:
    return width, max(1, round(width / aspect))


def _matrix(calib: FloorCalib, aspect: float, img_w: int, img_h: int, tw: int, th: int) -> np.ndarray:
    """Pixel da imagem -> pixel da textura (projetiva): imagem 0..1 -> retângulo do chão 0..1 -> zona local -> textura."""
    to_norm = np.array([[1.0 / img_w, 0, 0], [0, 1.0 / img_h, 0], [0, 0, 1.0]])
    k = calib.units_per_m(aspect)
    # retângulo do chão (u, v em 0..1) -> coordenada local da zona (x em 0..aspect, y em 0..1)
    to_local = np.array([[calib.width * k, 0, aspect / 2 - 0.5 * calib.width * k],
                         [0, calib.depth * k, 0.5 - 0.5 * calib.depth * k],
                         [0, 0, 1.0]])
    to_tex = np.array([[tw / aspect, 0, 0], [0, th, 0], [0, 0, 1.0]])
    return to_tex @ to_local @ calib._h() @ to_norm


def warp_floor(frame_bgr: np.ndarray, calib: FloorCalib, aspect: float, width: int = TEX_W) -> np.ndarray:
    """Textura BGRA (H, W, 4) da vista de cima da zona. Onde a câmera não vê (fora da imagem), alfa = 0."""
    img_h, img_w = frame_bgr.shape[:2]
    tw, th = tex_size(aspect, width)
    m = _matrix(calib, aspect, img_w, img_h, tw, th)
    color = cv2.warpPerspective(frame_bgr, m, (tw, th), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    seen = cv2.warpPerspective(np.full((img_h, img_w), 255, np.uint8), m, (tw, th), flags=cv2.INTER_NEAREST,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return np.dstack([color, seen])


class FloorMedian:
    """Mediana por pixel dos últimos `keep` quadros deformados: some quem passa, fica o que é fixo."""

    def __init__(self, keep: int = KEEP):
        self._keep = keep
        self._stack: List[np.ndarray] = []
        self.version = 0

    def add(self, tex_bgra: np.ndarray) -> None:
        if self._stack and self._stack[0].shape != tex_bgra.shape:        # mudou a proporção/tamanho: recomeça
            self._stack.clear()
        self._stack.append(tex_bgra)
        del self._stack[:-self._keep]
        self.version += 1

    @property
    def samples(self) -> int:
        return len(self._stack)

    def image(self) -> Optional[np.ndarray]:
        if not self._stack:
            return None
        if len(self._stack) < MIN_SAMPLES:
            return self._stack[-1]
        stack = np.stack(self._stack)                                      # (n, H, W, 4)
        med = np.median(stack[..., :3], axis=0).astype(np.uint8)
        alpha = stack[..., 3].max(axis=0)                                  # visto em algum quadro
        return np.dstack([med, alpha])

    def clear(self) -> None:
        self._stack.clear()
        self.version += 1
