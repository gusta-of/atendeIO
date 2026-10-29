/**
 * Geometria das formas (retângulo, quadrado, círculo/elipse, triângulo, polígono livre).
 * Lógica pura (sem DOM): portada de static/shapes.js sem mudar a matemática.
 *
 * - Pontos salvos são NORMALIZADOS (0..1). Girar neles distorceria a forma (a imagem não é quadrada),
 *   então a conta é feita em "espaço de pixels": X = x*W, Y = y*H.
 * - Formas primitivas são descritas por uma caixa orientada (OBB): {cx, cy, w, h, angle(rad)}.
 * - Polígono livre ("poly") não tem OBB: gira em torno do centro da sua caixa.
 */
import type { Point, ShapeKind } from '../core/models';

export interface Obb { cx: number; cy: number; w: number; h: number; angle: number; }
export interface Box { x0: number; y0: number; x1: number; y1: number; }

export const ELLIPSE_POINTS = 32;
const EPS = 1e-6;

export const deg2rad = (d: number): number => (d * Math.PI) / 180;
export const rad2deg = (r: number): number => (r * 180) / Math.PI;
/** Normaliza um ângulo (graus) para [-180, 180). */
export const wrapDeg = (d: number): number => ((((d + 180) % 360) + 360) % 360) - 180;

export function rot(x: number, y: number, a: number): Point {
  const c = Math.cos(a), s = Math.sin(a);
  return [x * c - y * s, x * s + y * c];
}

/** Contorno (em pixels) de uma forma primitiva descrita pela OBB. */
export function outline(shape: ShapeKind, obb: Obb): Point[] {
  const { cx, cy, w, h, angle } = obb;
  let local: Point[];
  if (shape === 'ellipse') {
    local = Array.from({ length: ELLIPSE_POINTS }, (_, i): Point => {
      const t = (2 * Math.PI * i) / ELLIPSE_POINTS;
      return [(w / 2) * Math.cos(t), (h / 2) * Math.sin(t)];
    });
  } else if (shape === 'triangle') {
    local = [[0, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];   // ponta pra cima
  } else {
    local = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];
  }
  return local.map(([lx, ly]): Point => {
    const [rx, ry] = rot(lx, ly, angle);
    return [cx + rx, cy + ry];
  });
}

export const toNorm = (pts: Point[], W: number, H: number): Point[] => pts.map(([x, y]): Point => [x / W, y / H]);
export const toPx = (pts: Point[], W: number, H: number): Point[] => pts.map(([x, y]): Point => [x * W, y * H]);

/** Pontos normalizados de uma forma primitiva. */
export const pointsFromObb = (shape: ShapeKind, obb: Obb, W: number, H: number): Point[] => toNorm(outline(shape, obb), W, H);

/** Recupera a OBB de uma forma salva (pontos normalizados + ângulo em graus). */
export function obbFromPoints(points: Point[], angleDeg: number, W: number, H: number): Obb {
  const a = deg2rad(angleDeg || 0);
  const local = toPx(points, W, H).map(([x, y]) => rot(x, y, -a));
  const xs = local.map((p) => p[0]), ys = local.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const [cx, cy] = rot((minX + maxX) / 2, (minY + maxY) / 2, a);
  return { cx, cy, w: maxX - minX, h: maxY - minY, angle: a };
}

/** OBB (sem rotação) de um arrasto "canto a canto". */
export const obbFromDrag = (x0: number, y0: number, x1: number, y1: number): Obb =>
  ({ cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, w: Math.abs(x1 - x0), h: Math.abs(y1 - y0), angle: 0 });

export const CORNER_SIGNS: Point[] = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
export const EDGE_SIGNS: Point[] = [[0, -1], [1, 0], [0, 1], [-1, 0]];   // topo, direita, base, esquerda (eixo local)

/** Posição (px) dos 4 cantos da OBB, na ordem de CORNER_SIGNS. */
export function corners(obb: Obb): Point[] {
  return CORNER_SIGNS.map(([sx, sy]): Point => {
    const [rx, ry] = rot((sx * obb.w) / 2, (sy * obb.h) / 2, obb.angle);
    return [obb.cx + rx, obb.cy + ry];
  });
}

/**
 * Redimensiona arrastando o canto `index`; o canto oposto fica parado (vale com a forma girada).
 * `keepRatio`: mantém a proporção largura/altura (quadrado, ou Shift no arrasto).
 */
export function resizeFromCorner(obb: Obb, index: number, pointer: Point, keepRatio = false): Obb {
  const [sx, sy] = CORNER_SIGNS[index];
  const fixed: Point = [(-sx * obb.w) / 2, (-sy * obb.h) / 2];
  const [px, py] = rot(pointer[0] - obb.cx, pointer[1] - obb.cy, -obb.angle);
  let w = Math.abs(px - fixed[0]), h = Math.abs(py - fixed[1]);
  let mx = (fixed[0] + px) / 2, my = (fixed[1] + py) / 2;
  if (keepRatio && obb.w > EPS && obb.h > EPS) {
    const k = Math.max(w / obb.w, h / obb.h);
    w = obb.w * k;
    h = obb.h * k;
    mx = fixed[0] + (px >= fixed[0] ? 1 : -1) * (w / 2);
    my = fixed[1] + (py >= fixed[1] ? 1 : -1) * (h / 2);
  }
  const [wx, wy] = rot(mx, my, obb.angle);
  return { cx: obb.cx + wx, cy: obb.cy + wy, w, h, angle: obb.angle };
}

/** Posição (px) do meio de cada lado da OBB, na ordem de EDGE_SIGNS. */
export function edgeMidpoints(obb: Obb): Point[] {
  return EDGE_SIGNS.map(([sx, sy]): Point => {
    const [rx, ry] = rot((sx * obb.w) / 2, (sy * obb.h) / 2, obb.angle);
    return [obb.cx + rx, obb.cy + ry];
  });
}

/** Arrasta o meio de um lado: muda SÓ a largura (esquerda/direita) ou SÓ a altura (topo/base). */
export function resizeFromEdge(obb: Obb, index: number, pointer: Point): Obb {
  const [sx, sy] = EDGE_SIGNS[index];
  const [px, py] = rot(pointer[0] - obb.cx, pointer[1] - obb.cy, -obb.angle);
  if (sx === 0) {
    const fixed = (-sy * obb.h) / 2;
    const [wx, wy] = rot(0, (fixed + py) / 2, obb.angle);
    return { cx: obb.cx + wx, cy: obb.cy + wy, w: obb.w, h: Math.abs(py - fixed), angle: obb.angle };
  }
  const fixed = (-sx * obb.w) / 2;
  const [wx, wy] = rot((fixed + px) / 2, 0, obb.angle);
  return { cx: obb.cx + wx, cy: obb.cy + wy, w: Math.abs(px - fixed), h: obb.h, angle: obb.angle };
}

/** Novo tamanho mantendo o centro (campos numéricos). */
export const withSize = (obb: Obb, w: number, h: number): Obb => ({ ...obb, w, h });

/** Ângulo (rad) da OBB para que a alça de rotação (acima do topo) aponte para o ponteiro. */
export const angleToward = (center: Point, pointer: Point): number =>
  Math.atan2(pointer[1] - center[1], pointer[0] - center[0]) + Math.PI / 2;

/** Posição (px) da alça de rotação: acima do centro do topo, `gap` px além da borda. */
export function rotateHandle(obb: Obb, gap = 28): Point {
  const [rx, ry] = rot(0, -obb.h / 2 - gap, obb.angle);
  return [obb.cx + rx, obb.cy + ry];
}

export function rotatePoints(pts: Point[], center: Point, delta: number): Point[] {
  return pts.map(([x, y]): Point => {
    const [rx, ry] = rot(x - center[0], y - center[1], delta);
    return [center[0] + rx, center[1] + ry];
  });
}

export function bbox(pts: Point[]): Box {
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
}

/**
 * Garante que a forma (px) fique dentro do quadro [0,W]x[0,H]: se passou da borda, empurra de volta.
 * Devolve null se a forma é maior que o quadro (não cabe) — o chamador descarta o passo.
 */
export function fitInside(pts: Point[], W: number, H: number): { points: Point[]; dx: number; dy: number } | null {
  const b = bbox(pts);
  if (b.x1 - b.x0 > W + EPS || b.y1 - b.y0 > H + EPS) return null;
  let dx = 0, dy = 0;
  if (b.x0 < 0) dx = -b.x0; else if (b.x1 > W) dx = W - b.x1;
  if (b.y0 < 0) dy = -b.y0; else if (b.y1 > H) dy = H - b.y1;
  return { points: pts.map(([x, y]): Point => [x + dx, y + dy]), dx, dy };
}

/**
 * Pontos (já em coordenadas do ícone `width`×`height`) de uma prévia da forma. Respeita a proporção da
 * imagem (`ar` = W/H): um retângulo girado aparece girado e um círculo continua redondo.
 * O template desenha: `<polygon [attr.points]="thumbPoints(...)">`.
 */
export function thumbPoints(points: Point[], ar: number, width = 34, height = 24): string {
  const px = points.map(([x, y]): Point => [x * ar, y]);
  const b = bbox(px);
  const bw = Math.max(b.x1 - b.x0, EPS), bh = Math.max(b.y1 - b.y0, EPS);
  const pad = 2, k = Math.min((width - 2 * pad) / bw, (height - 2 * pad) / bh);
  const ox = (width - bw * k) / 2 - b.x0 * k, oy = (height - bh * k) / 2 - b.y0 * k;
  return px.map(([x, y]) => `${(x * k + ox).toFixed(1)},${(y * k + oy).toFixed(1)}`).join(' ');
}

/** Contorno normalizado de cada forma "de catálogo" (ícones dos botões), no quadro 1:1. */
export function catalog(shape: ShapeKind): Point[] {
  if (shape === 'poly') return [[0.1, 0.3], [0.55, 0.05], [0.95, 0.4], [0.75, 0.95], [0.2, 0.8]];
  const obb: Obb = shape === 'rect' ? { cx: 0.5, cy: 0.5, w: 0.95, h: 0.6, angle: 0 }
    : shape === 'square' ? { cx: 0.5, cy: 0.5, w: 0.72, h: 0.72, angle: 0 }
    : { cx: 0.5, cy: 0.5, w: 0.8, h: 0.8, angle: 0 };
  return toNorm(outline(shape, obb), 1, 1);
}
