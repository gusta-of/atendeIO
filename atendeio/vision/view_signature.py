"""Assinatura da CENA de uma câmera, para saber se ela (ou o ambiente) mudou de posição.

Não guarda imagem: é um dHash de 16×16 células com máscara (64 bytes) tirado da MEDIANA de poucos quadros espaçados no tempo (quem passa pela cena some na
mediana). Dois dHash da mesma cena diferem pouco (luz, uma pessoa parada); uma câmera movida ou a mobília trocada muda a estrutura e a
distância sobe. Os 64 bytes não permitem reconstruir a imagem."""

from typing import List, Optional

import cv2
import numpy as np

HASH = 16
SIG_BYTES = HASH * HASH // 4          # 32 bytes de sinais + 32 de máscara (onde havia borda)
WINDOW = 5                    # quadros na mediana
EDGE = 4                      # diferença mínima (0..255) para a célula contar como borda
CHANGED_AT = 0.30             # fração de bits diferentes a partir da qual a cena é considerada outra


def _small(frame_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA), (3, 3), 0)


def signature_of(gray_small: np.ndarray) -> bytes:
    """dHash 16×16: o sinal da diferença horizontal entre vizinhos + uma máscara das células que têm borda (as lisas não contam)."""
    g = cv2.resize(gray_small, (HASH + 1, HASH), interpolation=cv2.INTER_AREA).astype(np.int16)
    diff = g[:, 1:] - g[:, :-1]
    sign = np.packbits((diff > 0).astype(np.uint8).ravel()).tobytes()
    valid = np.packbits((np.abs(diff) > EDGE).astype(np.uint8).ravel()).tobytes()
    return sign + valid


def distance(a: bytes, b: bytes) -> float:
    """0 = iguais ... ~0,5+ = sem relação, olhando só as células que têm borda em alguma das duas cenas."""
    if len(a) != SIG_BYTES or len(b) != SIG_BYTES:
        return 1.0
    n = SIG_BYTES // 2
    sa, va = np.unpackbits(np.frombuffer(a[:n], np.uint8)), np.unpackbits(np.frombuffer(a[n:], np.uint8))
    sb, vb = np.unpackbits(np.frombuffer(b[:n], np.uint8)), np.unpackbits(np.frombuffer(b[n:], np.uint8))
    active = (va | vb).sum()
    if active == 0:
        return 0.0
    wrong = (((sa ^ sb) & va & vb) | (va ^ vb)).sum()
    return float(wrong) / float(active)


class ViewWindow:
    """Janela de quadros (em baixa resolução, só memória) de onde sai a assinatura estável da cena."""

    def __init__(self, size: int = WINDOW):
        self._size = size
        self._frames: List[np.ndarray] = []

    def add(self, frame_bgr: np.ndarray) -> None:
        self._frames.append(_small(frame_bgr))
        del self._frames[:-self._size]

    @property
    def ready(self) -> bool:
        return len(self._frames) >= self._size

    def signature(self) -> Optional[bytes]:
        if not self.ready:
            return None
        return signature_of(np.median(np.stack(self._frames), axis=0).astype(np.uint8))

    def clear(self) -> None:
        self._frames.clear()
