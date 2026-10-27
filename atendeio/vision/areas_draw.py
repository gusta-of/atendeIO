"""Áreas "pintadas" no vídeo: contorno + preenchimento por baixo de quem está na frente.

Roda no servidor, quadro a quadro, antes do JPEG — o recorte da silhueta acompanha o vídeo (no
navegador ele ficaria atrasado, porque o estado chega a 1 Hz). Puro: só numpy/OpenCV, sem YOLO."""

from typing import Dict, Iterable, Optional

import cv2
import numpy as np

# BGR (o OpenCV usa B, G, R). Mesmas cores do painel.
STATUS_BGR = {"livre": (153, 211, 52), "ocupada": (113, 113, 248), "a_limpar": (36, 191, 251)}
KIND_BGR = {"mesa": (238, 211, 34), "balcao": (250, 139, 167), "entrada": (153, 211, 52),
            "saida": (60, 146, 251), "fila": (153, 114, 244), "area": (184, 163, 148)}
BLIND_BGR = (184, 163, 148)  # mesa sem leitura: cinza, não finge que está "livre"

FILL_ALPHA = 0.14
HALO_ALPHA = 0.40    # força da "sombra" de assentos junto da borda da mesa (some ao se afastar)
HALO_FALLOFF = 1.6
OUTLINE_PX = 2
EDGE_GROW_PX = 2     # a silhueta do modelo é irregular: cresce um pouco pra o contorno não "vazar" pela borda
EDGE_BLUR = 5        # e suaviza a borda, pra não ficar serrilhada


def zone_color(kind: str, status: Optional[str], blind: bool = False):
    if kind == "mesa":
        return BLIND_BGR if blind or status is None else STATUS_BGR.get(status, KIND_BGR["mesa"])
    return KIND_BGR.get(kind, KIND_BGR["area"])


def occlusion_mask(polys: Iterable, shape) -> np.ndarray:
    """Máscara float32 0..1 (1 = tem alguém na frente) de uma região `shape` (altura, largura),
    a partir de contornos já em pixels dessa região."""
    h, w = shape
    mask = np.zeros((h, w), np.uint8)
    for poly in polys:
        if len(poly) >= 3:
            cv2.fillPoly(mask, [np.asarray(poly, np.int32)], 255)
    if mask.any():
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * EDGE_GROW_PX + 1,) * 2)
        mask = cv2.GaussianBlur(cv2.dilate(mask, k), (EDGE_BLUR, EDGE_BLUR), 0)
    return mask.astype(np.float32) / 255.0


def draw_areas(frame: np.ndarray, zones: Iterable, statuses: Optional[Dict[int, str]] = None,
               occluders: Optional[Iterable] = None, blind: bool = False) -> None:
    """Desenha as áreas NO frame (em lugar), escondendo-as onde há oclusores.

    zones      objetos com .id, .kind e .points normalizados (analytics.zones.Zone)
    statuses   {zone_id: "livre"|"ocupada"|"a_limpar"} das mesas
    occluders  contornos normalizados de quem está na frente (pessoas, objetos); None = sem recorte
    blind      sem leitura (reconhecimento desligado etc.): mesas ficam cinza"""
    zones = list(zones)
    if not zones:
        return
    h, w = frame.shape[:2]
    px = {z.id: np.array([[x * w, y * h] for x, y in z.points], np.float32) for z in zones}

    # só mexe no retângulo que as áreas ocupam: é bem mais barato que o quadro inteiro
    allpts = np.concatenate(list(px.values()))
    halo_px = {z.id: float(getattr(z, "margin", 0.0)) * h for z in zones if z.kind == "mesa"}
    pad = OUTLINE_PX + 2 + int(max(halo_px.values(), default=0.0))
    x0, y0 = max(0, int(allpts[:, 0].min()) - pad), max(0, int(allpts[:, 1].min()) - pad)
    x1, y1 = min(w, int(allpts[:, 0].max()) + pad + 1), min(h, int(allpts[:, 1].max()) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return
    roi = frame[y0:y1, x0:x1]
    shift = np.array([x0, y0], np.float32)

    fill = roi.copy()
    for z in zones:
        color = zone_color(z.kind, (statuses or {}).get(z.id), blind)
        cv2.fillPoly(fill, [np.round(px[z.id] - shift).astype(np.int32)], color)
    layer = cv2.addWeighted(fill, FILL_ALPHA, roi, 1 - FILL_ALPHA, 0)  # fora das áreas: igual ao original
    for z in zones:  # sombra de assentos: degradê pra fora da mesa (quem senta ali conta na mesa)
        if halo_px.get(z.id, 0) >= 2:
            _paint_halo(layer, np.round(px[z.id] - shift).astype(np.int32), halo_px[z.id],
                        zone_color(z.kind, (statuses or {}).get(z.id), blind))
    for z in zones:
        color = zone_color(z.kind, (statuses or {}).get(z.id), blind)
        cv2.polylines(layer, [np.round(px[z.id] - shift).astype(np.int32)], True, color, OUTLINE_PX, cv2.LINE_AA)

    polys = [np.round(np.asarray(p, np.float32) * (w, h) - shift) for p in (occluders or [])]
    mask = occlusion_mask(polys, roi.shape[:2]) if polys else None
    if mask is None or not mask.any():
        roi[:] = layer
        return
    alpha = mask[..., None]                        # 1 onde há alguém na frente: fica o vídeo original
    roi[:] = (roi.astype(np.float32) * alpha + layer.astype(np.float32) * (1 - alpha)).astype(np.uint8)


def _paint_halo(layer: np.ndarray, poly: np.ndarray, margin_px: float, color) -> None:
    """Degradê de `color` ao redor de `poly` (fora dele), do mais forte na borda até sumir a `margin_px`.
    Trabalha numa janela do tamanho da mesa + margem, não no quadro inteiro."""
    lh, lw = layer.shape[:2]
    m = int(np.ceil(margin_px)) + 1
    x0, y0 = max(0, int(poly[:, 0].min()) - m), max(0, int(poly[:, 1].min()) - m)
    x1, y1 = min(lw, int(poly[:, 0].max()) + m + 1), min(lh, int(poly[:, 1].max()) + m + 1)
    if x1 <= x0 or y1 <= y0:
        return
    inside = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(inside, [poly - np.array([x0, y0], np.int32)], 255)
    dist = cv2.distanceTransform(255 - inside, cv2.DIST_L2, 3)       # px até a borda da mesa (0 dentro)
    alpha = np.clip(1.0 - dist / margin_px, 0.0, 1.0) ** HALO_FALLOFF * HALO_ALPHA
    alpha[inside > 0] = 0.0                                          # dentro já tem o preenchimento
    win = layer[y0:y1, x0:x1].astype(np.float32)
    win += (np.asarray(color, np.float32) - win) * alpha[..., None]
    layer[y0:y1, x0:x1] = win.astype(np.uint8)
