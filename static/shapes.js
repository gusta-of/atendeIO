/* atendeIO · Geometria das formas (retângulo, círculo/elipse, triângulo, polígono livre).
 *
 * Puro (sem DOM, exceto `thumb`): roda no navegador e no Node (testes em tests/js).
 *
 * Conceitos
 *  - Os pontos salvos são NORMALIZADOS (0..1). Girar neles distorceria a forma (a imagem não é
 *    quadrada), então toda a conta é feita em "espaço de pixels": X = x*W, Y = y*H.
 *  - Formas primitivas (rect, ellipse, triangle) são descritas por uma caixa orientada (OBB):
 *    {cx, cy, w, h, angle(rad)}. Os pontos saem dela; a OBB é recuperada dos pontos + ângulo salvo.
 *  - Polígono livre ("poly") não tem OBB: gira em torno do centro da sua caixa.
 */

"use strict";

(function (root) {
  const ELLIPSE_POINTS = 32;
  const EPS = 1e-6;
  const deg2rad = (d) => (d * Math.PI) / 180;
  const rad2deg = (r) => (r * 180) / Math.PI;

  function rot(x, y, a) {
    const c = Math.cos(a), s = Math.sin(a);
    return [x * c - y * s, x * s + y * c];
  }

  /** Contorno (em pixels) de uma forma primitiva descrita pela OBB. */
  function outline(shape, obb) {
    const { cx, cy, w, h, angle } = obb;
    let local;
    if (shape === "ellipse") {
      local = Array.from({ length: ELLIPSE_POINTS }, (_, i) => {
        const t = (2 * Math.PI * i) / ELLIPSE_POINTS;
        return [(w / 2) * Math.cos(t), (h / 2) * Math.sin(t)];
      });
    } else if (shape === "triangle") {
      local = [[0, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];  // ponta pra cima
    } else {
      local = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];
    }
    return local.map(([lx, ly]) => {
      const [rx, ry] = rot(lx, ly, angle);
      return [cx + rx, cy + ry];
    });
  }

  const toNorm = (pts, W, H) => pts.map(([x, y]) => [x / W, y / H]);
  const toPx = (pts, W, H) => pts.map(([x, y]) => [x * W, y * H]);

  /** Pontos normalizados de uma forma primitiva. */
  function pointsFromObb(shape, obb, W, H) {
    return toNorm(outline(shape, obb), W, H);
  }

  /** Recupera a OBB de uma forma salva (pontos normalizados + ângulo em graus). */
  function obbFromPoints(points, angleDeg, W, H) {
    const a = deg2rad(angleDeg || 0);
    const local = toPx(points, W, H).map(([x, y]) => rot(x, y, -a));
    const xs = local.map((p) => p[0]), ys = local.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const [cx, cy] = rot((minX + maxX) / 2, (minY + maxY) / 2, a);
    return { cx, cy, w: maxX - minX, h: maxY - minY, angle: a };
  }

  /** Pontos que a OBB resultante de um arrasto "canto a canto" (sem rotação) ocupa. */
  function obbFromDrag(x0, y0, x1, y1) {
    return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, w: Math.abs(x1 - x0), h: Math.abs(y1 - y0), angle: 0 };
  }

  const CORNER_SIGNS = [[-1, -1], [1, -1], [1, 1], [-1, 1]];

  /** Posição (px) dos 4 cantos da OBB, na ordem de CORNER_SIGNS. */
  function corners(obb) {
    return CORNER_SIGNS.map(([sx, sy]) => {
      const [rx, ry] = rot((sx * obb.w) / 2, (sy * obb.h) / 2, obb.angle);
      return [obb.cx + rx, obb.cy + ry];
    });
  }

  /**
   * Redimensiona arrastando o canto `index`; o canto oposto fica parado (vale com a forma girada).
   * `keepRatio`: mantém a proporção largura/altura (quadrado, ou Shift no arrasto).
   */
  function resizeFromCorner(obb, index, pointer, keepRatio = false) {
    const [sx, sy] = CORNER_SIGNS[index];
    const fixed = [(-sx * obb.w) / 2, (-sy * obb.h) / 2];                       // canto oposto, no eixo local
    const [px, py] = rot(pointer[0] - obb.cx, pointer[1] - obb.cy, -obb.angle);  // ponteiro no eixo local
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

  const EDGE_SIGNS = [[0, -1], [1, 0], [0, 1], [-1, 0]];  // topo, direita, base, esquerda (eixo local)

  /** Posição (px) do meio de cada lado da OBB, na ordem de EDGE_SIGNS. */
  function edgeMidpoints(obb) {
    return EDGE_SIGNS.map(([sx, sy]) => {
      const [rx, ry] = rot((sx * obb.w) / 2, (sy * obb.h) / 2, obb.angle);
      return [obb.cx + rx, obb.cy + ry];
    });
  }

  /** Arrasta o meio de um lado: muda SÓ a largura (esquerda/direita) ou SÓ a altura (topo/base). */
  function resizeFromEdge(obb, index, pointer) {
    const [sx, sy] = EDGE_SIGNS[index];
    const [px, py] = rot(pointer[0] - obb.cx, pointer[1] - obb.cy, -obb.angle);
    if (sx === 0) {  // topo/base: altura
      const fixed = (-sy * obb.h) / 2;
      const [wx, wy] = rot(0, (fixed + py) / 2, obb.angle);
      return { cx: obb.cx + wx, cy: obb.cy + wy, w: obb.w, h: Math.abs(py - fixed), angle: obb.angle };
    }
    const fixed = (-sx * obb.w) / 2;  // esquerda/direita: largura
    const [wx, wy] = rot((fixed + px) / 2, 0, obb.angle);
    return { cx: obb.cx + wx, cy: obb.cy + wy, w: Math.abs(px - fixed), h: obb.h, angle: obb.angle };
  }

  /** Novo tamanho mantendo o centro (campos numéricos). */
  const withSize = (obb, w, h) => ({ ...obb, w, h });

  /** Ângulo (rad) da OBB para que a alça de rotação (acima do topo) aponte para o ponteiro. */
  function angleToward(center, pointer) {
    return Math.atan2(pointer[1] - center[1], pointer[0] - center[0]) + Math.PI / 2;
  }

  /** Posição (px) da alça de rotação: acima do centro do topo, `gap` px além da borda. */
  function rotateHandle(obb, gap = 28) {
    const [rx, ry] = rot(0, -obb.h / 2 - gap, obb.angle);
    return [obb.cx + rx, obb.cy + ry];
  }

  function rotatePoints(pts, center, delta) {
    return pts.map(([x, y]) => {
      const [rx, ry] = rot(x - center[0], y - center[1], delta);
      return [center[0] + rx, center[1] + ry];
    });
  }

  function bbox(pts) {
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  }

  /**
   * Garante que a forma (px) fique dentro do quadro [0,W]x[0,H]: se passou da borda, empurra de volta.
   * Devolve null se a forma é maior que o quadro (não cabe) — o chamador descarta o passo.
   */
  function fitInside(pts, W, H) {
    const b = bbox(pts);
    if (b.x1 - b.x0 > W + EPS || b.y1 - b.y0 > H + EPS) return null;
    let dx = 0, dy = 0;
    if (b.x0 < 0) dx = -b.x0; else if (b.x1 > W) dx = W - b.x1;
    if (b.y0 < 0) dy = -b.y0; else if (b.y1 > H) dy = H - b.y1;
    return { points: pts.map(([x, y]) => [x + dx, y + dy]), dx, dy };
  }

  /** Normaliza um ângulo (graus) para [-180, 180). */
  const wrapDeg = (d) => ((((d + 180) % 360) + 360) % 360) - 180;

  /**
   * Prévia da forma (SVG) para listas e botões. Respeita a proporção da imagem (`ar` = W/H),
   * então um retângulo girado aparece girado e um círculo continua redondo.
   */
  function thumb(points, { ar = 16 / 9, color = "#22d3ee", width = 34, height = 24, fill = 0.35 } = {}) {
    const ns = "http://www.w3.org/2000/svg";
    const px = points.map(([x, y]) => [x * ar, y]);
    const b = bbox(px);
    const bw = Math.max(b.x1 - b.x0, EPS), bh = Math.max(b.y1 - b.y0, EPS);
    const pad = 2, k = Math.min((width - 2 * pad) / bw, (height - 2 * pad) / bh);
    const ox = (width - bw * k) / 2 - b.x0 * k, oy = (height - bh * k) / 2 - b.y0 * k;
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("aria-hidden", "true");
    svg.classList.add("shape-thumb");
    const poly = document.createElementNS(ns, "polygon");
    poly.setAttribute("points", px.map(([x, y]) => `${(x * k + ox).toFixed(1)},${(y * k + oy).toFixed(1)}`).join(" "));
    poly.setAttribute("fill", color);
    poly.setAttribute("fill-opacity", String(fill));
    poly.setAttribute("stroke", color);
    poly.setAttribute("stroke-width", "1.5");
    poly.setAttribute("stroke-linejoin", "round");
    svg.append(poly);
    return svg;
  }

  /** Contorno normalizado de cada forma "de catálogo" (ícones dos botões), no quadro 1:1. */
  function catalog(shape) {
    const obb = shape === "rect" ? { cx: 0.5, cy: 0.5, w: 0.95, h: 0.6, angle: 0 }
      : shape === "square" ? { cx: 0.5, cy: 0.5, w: 0.72, h: 0.72, angle: 0 }
      : { cx: 0.5, cy: 0.5, w: 0.8, h: 0.8, angle: 0 };
    if (shape === "poly") return [[0.1, 0.3], [0.55, 0.05], [0.95, 0.4], [0.75, 0.95], [0.2, 0.8]];
    return toNorm(outline(shape, obb), 1, 1);
  }

  const api = {
    ELLIPSE_POINTS, CORNER_SIGNS, deg2rad, rad2deg, wrapDeg, rot, outline, toNorm, toPx, pointsFromObb,
    obbFromPoints, obbFromDrag, corners, resizeFromCorner, EDGE_SIGNS, edgeMidpoints, resizeFromEdge, withSize, angleToward, rotateHandle, rotatePoints, bbox,
    fitInside, thumb, catalog,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Shapes = api;
})(typeof window !== "undefined" ? window : globalThis);
