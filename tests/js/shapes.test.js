// Rode com: node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("../../static/shapes.js");

const W = 640, H = 480;
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("retângulo: pontos <-> OBB fazem ida e volta, com e sem rotação", () => {
  for (const deg of [0, 30, 90, -45, 137]) {
    const obb = { cx: 300, cy: 200, w: 120, h: 60, angle: S.deg2rad(deg) };
    const pts = S.pointsFromObb("rect", obb, W, H);
    const back = S.obbFromPoints(pts, deg, W, H);
    close(back.cx, 300); close(back.cy, 200); close(back.w, 120); close(back.h, 60);
  }
});

test("círculo/elipse e triângulo recuperam centro e tamanho", () => {
  for (const shape of ["ellipse", "triangle"]) {
    const obb = { cx: 320, cy: 240, w: 100, h: 80, angle: S.deg2rad(25) };
    const back = S.obbFromPoints(S.pointsFromObb(shape, obb, W, H), 25, W, H);
    close(back.cx, 320, 1e-3); close(back.cy, 240, 1e-3); close(back.w, 100, 1e-3); close(back.h, 80, 1e-3);
  }
});

test("girar 90° troca largura por altura nos pontos e preserva a área", () => {
  const area = (p) => Math.abs(p.reduce((s, [x, y], i) => s + x * p[(i + 1) % p.length][1] - p[(i + 1) % p.length][0] * y, 0)) / 2;
  const a = S.outline("rect", { cx: 300, cy: 200, w: 120, h: 40, angle: 0 });
  const b = S.outline("rect", { cx: 300, cy: 200, w: 120, h: 40, angle: Math.PI / 2 });
  close(area(a), area(b), 1e-6);
  const bb = S.bbox(b);
  close(bb.x1 - bb.x0, 40, 1e-6); close(bb.y1 - bb.y0, 120, 1e-6);
});

test("triângulo tem a ponta pra cima e a base embaixo", () => {
  const [apex, br, bl] = S.outline("triangle", { cx: 100, cy: 100, w: 60, h: 40, angle: 0 });
  assert.deepEqual(apex.map(Math.round), [100, 80]);
  assert.deepEqual(br.map(Math.round), [130, 120]);
  assert.deepEqual(bl.map(Math.round), [70, 120]);
});

test("círculo tem 32 pontos, todos a mesma distância do centro quando w=h", () => {
  const pts = S.outline("ellipse", { cx: 200, cy: 200, w: 100, h: 100, angle: 0.7 });
  assert.equal(pts.length, 32);
  for (const [x, y] of pts) close(Math.hypot(x - 200, y - 200), 50, 1e-6);
});

test("redimensionar pelo canto mantém o canto oposto parado, mesmo girado", () => {
  const obb = { cx: 300, cy: 200, w: 100, h: 60, angle: S.deg2rad(40) };
  const before = S.corners(obb);
  // arrasta o canto 2 (+,+) para mais longe, ao longo da diagonal local
  const target = S.rot(80, 50, obb.angle);
  const next = S.resizeFromCorner(obb, 2, [obb.cx + target[0], obb.cy + target[1]]);
  const after = S.corners(next);
  close(after[0][0], before[0][0], 1e-6); close(after[0][1], before[0][1], 1e-6);  // canto 0 (oposto) não saiu do lugar
  close(next.w, 130, 1e-6); close(next.h, 80, 1e-6);
  close(next.angle, obb.angle);
});

test("a alça de rotação fica acima do topo e o ângulo volta ao apontar pra ela", () => {
  const obb = { cx: 300, cy: 200, w: 100, h: 60, angle: 0 };
  const hnd = S.rotateHandle(obb, 28);
  close(hnd[0], 300); close(hnd[1], 200 - 30 - 28);
  close(S.angleToward([300, 200], hnd), 0);
  const turned = { ...obb, angle: S.deg2rad(60) };
  close(S.angleToward([300, 200], S.rotateHandle(turned)), S.deg2rad(60), 1e-9);
});

test("rotatePoints preserva distâncias ao pivô", () => {
  const pts = [[10, 10], [50, 10], [30, 40]];
  const out = S.rotatePoints(pts, [30, 20], S.deg2rad(77));
  pts.forEach((p, i) => close(Math.hypot(p[0] - 30, p[1] - 20), Math.hypot(out[i][0] - 30, out[i][1] - 20), 1e-9));
});

test("fitInside empurra a forma de volta pro quadro e recusa a que não cabe", () => {
  const out = S.fitInside([[-10, 20], [50, 20], [50, 80]], W, H);
  assert.equal(out.dx, 10);
  assert.ok(out.points.every(([x]) => x >= 0));
  assert.equal(S.fitInside([[0, 0], [W + 50, 0], [0, 10]], W, H), null);
});

test("wrapDeg", () => {
  assert.equal(S.wrapDeg(190), -170);
  assert.equal(S.wrapDeg(-190), 170);
  assert.equal(S.wrapDeg(180), -180);
  assert.equal(S.wrapDeg(45), 45);
});

test("lado do meio muda só a largura ou só a altura, mesmo girado", () => {
  const obb = { cx: 300, cy: 200, w: 100, h: 60, angle: S.deg2rad(30) };
  // arrasta a borda direita (índice 1) 40 px pra fora, ao longo do eixo local x
  const out = S.rot(50 + 40, 0, obb.angle);
  const r = S.resizeFromEdge(obb, 1, [obb.cx + out[0], obb.cy + out[1]]);
  close(r.w, 140); close(r.h, 60);                                   // só a largura cresceu
  const left0 = S.edgeMidpoints(obb)[3], left1 = S.edgeMidpoints(r)[3];
  close(left1[0], left0[0], 1e-6); close(left1[1], left0[1], 1e-6);  // a borda esquerda ficou parada
  // topo (índice 0) puxado pra cima: só a altura muda
  const up = S.rot(0, -30 - 20, obb.angle);
  const t = S.resizeFromEdge(obb, 0, [obb.cx + up[0], obb.cy + up[1]]);
  close(t.w, 100); close(t.h, 80);
});

test("keepRatio preserva a proporção ao arrastar o canto (quadrado continua quadrado)", () => {
  const sq = { cx: 200, cy: 200, w: 80, h: 80, angle: 0 };
  // arrasta o canto (+,+) pra (320, 280): o lado vira o maior movimento, e fica quadrado
  const r = S.resizeFromCorner(sq, 2, [320, 280], true);
  close(r.w, r.h, 1e-9);
  close(r.w, 160, 1e-9);                                             // fixo em (160,160) -> lado = 320-160
  const tl = S.corners(r)[0];
  close(tl[0], 160); close(tl[1], 160);                              // canto oposto parado
  const free = S.resizeFromCorner(sq, 2, [320, 280], false);        // sem trava: retângulo
  close(free.w, 160); close(free.h, 120);
});

test("withSize troca o tamanho e mantém centro e ângulo", () => {
  const o = S.withSize({ cx: 50, cy: 60, w: 10, h: 20, angle: 1 }, 30, 40);
  assert.deepEqual([o.cx, o.cy, o.w, o.h, o.angle], [50, 60, 30, 40, 1]);
});

test("quadrado tem lados iguais e o ícone do retângulo é mais largo que alto", () => {
  const sq = S.outline("square", { cx: 100, cy: 100, w: 60, h: 60, angle: 0 });
  close(Math.hypot(sq[1][0] - sq[0][0], sq[1][1] - sq[0][1]), Math.hypot(sq[2][0] - sq[1][0], sq[2][1] - sq[1][1]));
  const b = S.bbox(S.catalog("rect")), q = S.bbox(S.catalog("square"));
  assert.ok((b.x1 - b.x0) > (b.y1 - b.y0) * 1.3);
  close(q.x1 - q.x0, q.y1 - q.y0, 1e-9);
});
