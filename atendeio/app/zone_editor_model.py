"""Lógica do editor de áreas (sem Qt): ferramentas, desenhar, mover, redimensionar, girar, polígono, nomes e dados a salvar.

Porta de `web/src/app/features/zones/zone-editor.modal.ts`. As coordenadas SALVAS são sempre normalizadas (0..1); a edição
acontece em pixels do quadro exibido (`W` x `H`). O widget só traduz mouse/teclado nestes métodos e desenha o resultado."""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import shapes as S
from .labels import KIND_LABEL

DEFAULT_MARGIN = 0.06   # sombra de assentos: 6% da altura da imagem
MAX_MARGIN = 0.25
MIN_PX = 14             # forma menor que isso é clique perdido, não uma mesa
CLOSE_DIST_PX = 12      # clicar perto do 1º ponto fecha o polígono
SNAP_DEG = 15
HANDLE_RADIUS = 9

TOOLS = [("select", "Selecionar", "V", "Mover, redimensionar e girar áreas"),
         ("rect", "Retângulo", "R", "Arraste sobre o vídeo"),
         ("square", "Quadrado", "Q", "Arraste sobre o vídeo (os lados ficam sempre iguais)"),
         ("ellipse", "Círculo", "C", "Arraste sobre o vídeo (vira elipse se não for quadrado)"),
         ("triangle", "Triângulo", "T", "Arraste sobre o vídeo"),
         ("poly", "Polígono", "P", "Clique nos cantos; clique no 1º ponto, duplo clique ou Enter para fechar")]
SHAPE_LABEL = {"rect": "Retângulo", "square": "Quadrado", "ellipse": "Círculo", "triangle": "Triângulo", "poly": "Polígono"}
Point = Tuple[float, float]


def clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


@dataclass
class DragDraft:
    shape: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class PolyDraft:
    pts: List[Point] = field(default_factory=list)
    hover: Optional[Point] = None


def point_in_polygon(p: Point, poly: List[Point]) -> bool:
    x, y, inside = p[0], p[1], False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


class EditorModel:
    def __init__(self, zones: List[dict], W: float = 1, H: float = 1, video_size: Optional[Tuple[int, int]] = None):
        self.zones: List[dict] = [{
            "id": z.get("id"), "name": z.get("name", ""), "kind": z["kind"], "shape": z.get("shape") or "poly",
            "angle": float(z.get("angle") or 0),
            "margin": z["margin"] if z.get("margin") is not None else (DEFAULT_MARGIN if z["kind"] == "mesa" else 0.0),
            "points": [(float(p[0]), float(p[1])) for p in z["points"]],
        } for z in zones]
        self.W, self.H = max(W, 1), max(H, 1)
        self.video_size = video_size          # tamanho real do vídeo (px): os campos de largura/altura usam estes pixels
        self.sel: Optional[int] = None
        self.tool = "select"
        self.draft = None                     # DragDraft | PolyDraft | None
        self.drag: Optional[dict] = None
        self.dirty = False
        self.lock_ratio = False
        self.error = ""

    # -- consulta ---------------------------------------------------------------------------------
    @property
    def selected(self) -> Optional[dict]:
        return self.zones[self.sel] if self.sel is not None and 0 <= self.sel < len(self.zones) else None

    @property
    def aspect(self) -> float:
        return self.W / self.H

    def set_frame(self, w: float, h: float) -> None:
        self.W, self.H = max(w, 1), max(h, 1)

    def bad(self, z: dict) -> bool:
        """Nome vazio ou repetido impede salvar (o serviço também recusa)."""
        k = z["name"].strip().lower()
        return not k or sum(1 for o in self.zones if o["name"].strip().lower() == k) > 1

    @property
    def invalid(self) -> bool:
        return any(self.bad(z) for z in self.zones)

    def is_primitive(self, z: Optional[dict]) -> bool:
        return bool(z) and z["shape"] in S.PRIMITIVES

    def _vw(self) -> float:
        return (self.video_size[0] if self.video_size else 0) or self.W

    def _vh(self) -> float:
        return (self.video_size[1] if self.video_size else 0) or self.H

    def size_w(self) -> int:
        z = self.selected
        return round(self._obb(z).w * self._vw() / self.W) if self.is_primitive(z) else 0

    def size_h(self) -> int:
        z = self.selected
        return round(self._obb(z).h * self._vh() / self.H) if self.is_primitive(z) else 0

    def hint(self) -> str:
        if self.tool == "select":
            return ("Arraste para mover. Cantos redimensionam (Shift mantém a proporção), quadradinhos dos lados mudam só a "
                    "largura ou só a altura, a bolinha de cima gira." if self.selected else "Clique numa área para editar.")
        return next(t[3] for t in TOOLS if t[0] == self.tool) + ". Esc cancela."

    def _px(self, z: dict) -> List[Point]:
        return S.to_px(z["points"], self.W, self.H)

    def _obb(self, z: dict) -> S.Obb:
        return S.obb_from_points(z["points"], z["angle"], self.W, self.H)

    # -- alças (para desenhar e para o clique) ----------------------------------------------------------
    def handles(self) -> Optional[dict]:
        z = self.selected
        if not z or self.tool != "select":
            return None
        pts = self._px(z)
        edges, corners, verts = [], [], []
        if z["shape"] in S.PRIMITIVES:
            obb = self._obb(z)
            if z["shape"] != "square":
                edges = [(x, y, i, S.rad2deg(obb.angle)) for i, (x, y) in enumerate(S.edge_midpoints(obb))]
            corners = [(x, y, i) for i, (x, y) in enumerate(S.corners(obb))]
            at = S.rotate_handle(obb, 28)
            top = S.rot(0, -obb.h / 2, obb.angle)
            pivot = (obb.cx + top[0], obb.cy + top[1])
        else:
            verts = [(x, y, i) for i, (x, y) in enumerate(pts)]
            b = S.bbox(pts)
            pivot = ((b.x0 + b.x1) / 2, b.y0)
            at = (pivot[0], max(12, pivot[1] - 28))
        at = (clamp(at[0], 10, self.W - 10), clamp(at[1], 10, self.H - 10))
        return {"edges": edges, "corners": corners, "verts": verts, "pivot": pivot, "at": at}

    def hit_test(self, p: Point):
        """O que está sob o ponteiro: ('handle', 'c0'|'e1'|'v2'|'rot') ou ('zone', i) ou None."""
        h = self.handles()
        if h:
            if math.hypot(p[0] - h["at"][0], p[1] - h["at"][1]) <= HANDLE_RADIUS + 1:
                return ("handle", "rot")
            for prefix, items in (("c", h["corners"]), ("v", h["verts"])):
                for x, y, i in items:
                    if math.hypot(p[0] - x, p[1] - y) <= HANDLE_RADIUS:
                        return ("handle", f"{prefix}{i}")
            for x, y, i, _deg in h["edges"]:
                if math.hypot(p[0] - x, p[1] - y) <= HANDLE_RADIUS:
                    return ("handle", f"e{i}")
        for i in range(len(self.zones) - 1, -1, -1):
            if point_in_polygon(p, self._px(self.zones[i])):
                return ("zone", i)
        return None

    # -- edição de dados ---------------------------------------------------------------------------
    def _patch(self, i: int, **kw) -> None:
        self.zones[i].update(kw)
        self.dirty = True

    def _set_pixels(self, i: int, pts: List[Point], **extra) -> bool:
        """Aplica pontos (px) à zona; garante que ficam dentro do quadro. False se não couber."""
        fitted = S.fit_inside(pts, self.W, self.H)
        if not fitted:
            return False
        self._patch(i, points=S.to_norm(fitted[0], self.W, self.H), **extra)
        return True

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.draft = None
        self.drag = None
        if tool != "select":
            self.sel = None

    def select(self, i: Optional[int]) -> None:
        self.sel = i

    def pick(self, i: int) -> None:
        self.set_tool("select")
        self.select(i)

    def set_name(self, v: str) -> None:
        if self.selected is not None:
            self._patch(self.sel, name=v)

    def set_kind(self, kind: str) -> None:
        z = self.selected
        if z is not None:
            self._patch(self.sel, kind=kind, margin=DEFAULT_MARGIN if kind == "mesa" and not z["margin"] else z["margin"])

    def set_seat_pct(self, pct: float) -> None:
        if self.selected is not None and math.isfinite(pct):
            self._patch(self.sel, margin=clamp(pct, 0, MAX_MARGIN * 100) / 100)

    def remove(self) -> None:
        if self.sel is None:
            return
        del self.zones[self.sel]
        self.sel = None
        self.dirty = True

    def auto_name(self, kind: str) -> str:
        base = KIND_LABEL[kind]
        used = {z["name"].strip().lower() for z in self.zones}
        if kind != "mesa" and base.lower() not in used:
            return base
        n = 1
        while f"{base} {n}".lower() in used:
            n += 1
        return f"{base} {n}"

    def add_zone(self, shape: str, points_px: List[Point]) -> None:
        self.zones.append({"id": None, "name": self.auto_name("mesa"), "kind": "mesa", "shape": shape, "angle": 0.0,
                           "margin": DEFAULT_MARGIN, "points": S.to_norm(points_px, self.W, self.H)})
        self.dirty = True
        self.set_tool("select")
        self.select(len(self.zones) - 1)

    def finish_poly(self) -> None:
        d = self.draft
        if not isinstance(d, PolyDraft):
            return
        pts: List[Point] = []
        for p in d.pts:                    # um duplo clique registra o último ponto duas vezes
            if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 4:
                pts.append(p)
        self.draft = None
        if len(pts) >= 3:
            self.add_zone("poly", pts)

    def rotate_to(self, i: int, target_deg: float) -> bool:
        """Rotação (valor absoluto em graus; o Shift trava em passos)."""
        z = self.zones[i]
        target = S.wrap_deg(target_deg)
        if z["shape"] in S.PRIMITIVES:
            o = self._obb(z)
            return self._set_pixels(i, S.outline(z["shape"], S.Obb(o.cx, o.cy, o.w, o.h, S.deg2rad(target))), angle=target)
        pts = self._px(z)
        b = S.bbox(pts)
        return self._set_pixels(i, S.rotate_points(pts, ((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2), S.deg2rad(target - z["angle"])),
                                angle=target)

    def set_angle(self, deg: float) -> None:
        if self.sel is not None and math.isfinite(deg):
            self.rotate_to(self.sel, clamp(deg, -180, 180))

    def apply_size(self, changed: str, w_px: float, h_px: float) -> bool:
        """Largura/altura digitadas (px do vídeo). Quadrado e "manter proporção" ligam os dois campos.
        False se a forma não cabe na imagem com esse tamanho."""
        z = self.selected
        if z is None or not self.is_primitive(z) or not (w_px > 0 and h_px > 0):
            return True
        kx, ky = self.W / self._vw(), self.H / self._vh()
        o = self._obb(z)
        ratio = o.w / o.h
        wv, hv = w_px, h_px
        if z["shape"] == "square":
            hv = wv
        elif self.lock_ratio:
            if changed == "w":
                hv = wv / ratio
            else:
                wv = hv * ratio
        nxt = S.with_size(o, max(MIN_PX, wv * kx), max(MIN_PX, hv * ky))
        return self._set_pixels(self.sel, S.outline(z["shape"], nxt))

    # -- ponteiro ------------------------------------------------------------------------------------
    def clamp_point(self, p: Point) -> Point:
        return (clamp(p[0], 0, self.W), clamp(p[1], 0, self.H))

    def pointer_down(self, p: Point, shift: bool = False) -> None:
        p = self.clamp_point(p)
        tool = self.tool
        if tool == "select":
            hit = self.hit_test(p)
            z = self.selected
            if hit and hit[0] == "handle" and z is not None:
                h = hit[1]
                if h == "rot":
                    center = self._rotation_center(z)
                    self.drag = {"type": "rotate", "center": center, "start_ptr": S.angle_toward(center, p),
                                 "start_angle": z["angle"]}
                elif h[0] == "c":
                    self.drag = {"type": "corner", "index": int(h[1:]), "obb": self._obb(z)}
                elif h[0] == "e":
                    self.drag = {"type": "edge", "index": int(h[1:]), "obb": self._obb(z)}
                else:
                    self.drag = {"type": "vertex", "vi": int(h[1:])}
            elif hit and hit[0] == "zone":
                if hit[1] != self.sel:
                    self.select(hit[1])
                self.drag = {"type": "move", "last": p}
            else:
                self.select(None)
        elif tool in S.PRIMITIVES:
            self.draft = DragDraft(tool, p[0], p[1], p[0], p[1])
            self.drag = {"type": "draw"}
        elif tool == "poly":
            cur = self.draft if isinstance(self.draft, PolyDraft) else PolyDraft()
            if len(cur.pts) >= 3 and math.hypot(p[0] - cur.pts[0][0], p[1] - cur.pts[0][1]) <= CLOSE_DIST_PX:
                self.draft = cur
                self.finish_poly()
                return
            cur.pts.append(p)
            self.draft = cur

    def _rotation_center(self, z: dict) -> Point:
        if self.is_primitive(z):
            o = self._obb(z)
            return (o.cx, o.cy)
        b = S.bbox(self._px(z))
        return ((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)

    def pointer_move(self, p: Point, shift: bool = False) -> None:
        p = self.clamp_point(p)
        d = self.draft
        if isinstance(d, PolyDraft):
            d.hover = p
            return
        drag, i = self.drag, self.sel
        if not drag:
            return
        if drag["type"] == "draw" and isinstance(d, DragDraft):
            x1, y1 = p
            if d.shape == "square" or (shift and d.shape != "triangle"):          # lados iguais
                s = max(abs(p[0] - d.x0), abs(p[1] - d.y0))
                x1 = d.x0 + math.copysign(1, (p[0] - d.x0) or 1) * s
                y1 = d.y0 + math.copysign(1, (p[1] - d.y0) or 1) * s
            d.x1, d.y1 = x1, y1
            return
        z = self.selected
        if i is None or z is None:
            return
        t = drag["type"]
        if t == "move":
            pts = self._px(z)
            b = S.bbox(pts)
            dx = clamp(p[0] - drag["last"][0], -b.x0, self.W - b.x1)               # não sai da imagem
            dy = clamp(p[1] - drag["last"][1], -b.y0, self.H - b.y1)
            self._set_pixels(i, [(x + dx, y + dy) for x, y in pts])
            drag["last"] = (drag["last"][0] + dx, drag["last"][1] + dy)
        elif t == "corner":
            keep = shift or z["shape"] == "square" or self.lock_ratio
            o = S.resize_from_corner(drag["obb"], drag["index"], p, keep)
            if o.w >= MIN_PX and o.h >= MIN_PX:
                self._set_pixels(i, S.outline(z["shape"], o))
        elif t == "edge":
            o = S.resize_from_edge(drag["obb"], drag["index"], p)
            if o.w >= MIN_PX and o.h >= MIN_PX:
                self._set_pixels(i, S.outline(z["shape"], o))
        elif t == "vertex":
            pts = self._px(z)
            pts[drag["vi"]] = p
            self._set_pixels(i, pts)
        elif t == "rotate":
            deg = drag["start_angle"] + S.rad2deg(S.angle_toward(drag["center"], p) - drag["start_ptr"])
            if shift:
                deg = round(deg / SNAP_DEG) * SNAP_DEG
            self.rotate_to(i, deg)

    def pointer_up(self) -> None:
        drag, d = self.drag, self.draft
        self.drag = None
        if drag and drag["type"] == "draw" and isinstance(d, DragDraft):
            self.draft = None
            if abs(d.x1 - d.x0) >= MIN_PX and abs(d.y1 - d.y0) >= MIN_PX:
                self.add_zone(d.shape, S.outline(d.shape, S.obb_from_drag(d.x0, d.y0, d.x1, d.y1)))

    def double_click(self) -> None:
        self.finish_poly()

    # -- teclado -----------------------------------------------------------------------------------------
    def key(self, key: str, shift: bool = False, typing: bool = False) -> Optional[str]:
        """Trata uma tecla. Devolve "close" quando Esc pede para fechar o editor."""
        d, i = self.draft, self.sel
        if key == "Escape":
            if d is not None:
                self.draft, self.drag = None, None
            elif i is not None:
                self.select(None)
            else:
                return "close"
        elif key == "Enter" and isinstance(d, PolyDraft):
            self.finish_poly()
        elif key == "Backspace" and isinstance(d, PolyDraft) and not typing:
            d.pts = d.pts[:-1]
        elif key in ("Delete", "Backspace") and i is not None and not typing:
            self.remove()
        elif key in ("[", "]") and i is not None and not typing:
            self.set_angle(self.zones[i]["angle"] + (1 if key == "]" else -1) * (SNAP_DEG if shift else 5))
        elif not typing:
            for tool_id, _label, hotkey, _hint in TOOLS:
                if hotkey.lower() == key.lower():
                    self.set_tool(tool_id)
        return None

    # -- salvar ------------------------------------------------------------------------------------------
    def payload(self) -> List[dict]:
        return [{"id": z["id"], "name": z["name"].strip(), "kind": z["kind"], "shape": z["shape"], "angle": z["angle"],
                 "margin": z["margin"] if z["kind"] == "mesa" else 0.0,
                 "points": [[round(x, 5), round(y, 5)] for x, y in z["points"]]} for z in self.zones]
