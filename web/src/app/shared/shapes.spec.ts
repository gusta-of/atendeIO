import { describe, expect, it } from 'vitest';

import * as S from './shapes';
import type { Point } from '../core/models';

const W = 640, H = 480;
const close = (a: number, b: number, eps = 1e-6) => expect(Math.abs(a - b)).toBeLessThan(eps);

describe('shapes', () => {
  it('retângulo: pontos <-> OBB fazem ida e volta, com e sem rotação', () => {
    for (const deg of [0, 30, 90, -45, 137]) {
      const obb = { cx: 300, cy: 200, w: 120, h: 60, angle: S.deg2rad(deg) };
      const back = S.obbFromPoints(S.pointsFromObb('rect', obb, W, H), deg, W, H);
      close(back.cx, 300); close(back.cy, 200); close(back.w, 120); close(back.h, 60);
    }
  });

  it('círculo/elipse e triângulo recuperam centro e tamanho', () => {
    for (const shape of ['ellipse', 'triangle'] as const) {
      const obb = { cx: 320, cy: 240, w: 100, h: 80, angle: S.deg2rad(25) };
      const back = S.obbFromPoints(S.pointsFromObb(shape, obb, W, H), 25, W, H);
      close(back.cx, 320, 1e-3); close(back.cy, 240, 1e-3); close(back.w, 100, 1e-3); close(back.h, 80, 1e-3);
    }
  });

  it('girar 90° troca largura por altura e preserva a área', () => {
    const area = (p: Point[]) => Math.abs(p.reduce((s, [x, y], i) => s + x * p[(i + 1) % p.length][1] - p[(i + 1) % p.length][0] * y, 0)) / 2;
    const a = S.outline('rect', { cx: 300, cy: 200, w: 120, h: 40, angle: 0 });
    const b = S.outline('rect', { cx: 300, cy: 200, w: 120, h: 40, angle: Math.PI / 2 });
    close(area(a), area(b), 1e-6);
    const bb = S.bbox(b);
    close(bb.x1 - bb.x0, 40); close(bb.y1 - bb.y0, 120);
  });

  it('triângulo tem a ponta pra cima e a base embaixo', () => {
    const [apex, br, bl] = S.outline('triangle', { cx: 100, cy: 100, w: 60, h: 40, angle: 0 });
    expect(apex.map(Math.round)).toEqual([100, 80]);
    expect(br.map(Math.round)).toEqual([130, 120]);
    expect(bl.map(Math.round)).toEqual([70, 120]);
  });

  it('círculo tem 32 pontos, todos à mesma distância do centro quando w=h', () => {
    const pts = S.outline('ellipse', { cx: 200, cy: 200, w: 100, h: 100, angle: 0.7 });
    expect(pts.length).toBe(32);
    for (const [x, y] of pts) close(Math.hypot(x - 200, y - 200), 50);
  });

  it('redimensionar pelo canto mantém o canto oposto parado, mesmo girado', () => {
    const obb = { cx: 300, cy: 200, w: 100, h: 60, angle: S.deg2rad(40) };
    const before = S.corners(obb);
    const target = S.rot(80, 50, obb.angle);
    const next = S.resizeFromCorner(obb, 2, [obb.cx + target[0], obb.cy + target[1]]);
    const after = S.corners(next);
    close(after[0][0], before[0][0]); close(after[0][1], before[0][1]);
    close(next.w, 130); close(next.h, 80); close(next.angle, obb.angle);
  });

  it('a alça de rotação fica acima do topo e o ângulo volta ao apontar pra ela', () => {
    const obb = { cx: 300, cy: 200, w: 100, h: 60, angle: 0 };
    const hnd = S.rotateHandle(obb, 28);
    close(hnd[0], 300); close(hnd[1], 200 - 30 - 28);
    close(S.angleToward([300, 200], hnd), 0);
    const turned = { ...obb, angle: S.deg2rad(60) };
    close(S.angleToward([300, 200], S.rotateHandle(turned)), S.deg2rad(60), 1e-9);
  });

  it('rotatePoints preserva distâncias ao pivô', () => {
    const pts: Point[] = [[10, 10], [50, 10], [30, 40]];
    const out = S.rotatePoints(pts, [30, 20], S.deg2rad(77));
    pts.forEach((p, i) => close(Math.hypot(p[0] - 30, p[1] - 20), Math.hypot(out[i][0] - 30, out[i][1] - 20), 1e-9));
  });

  it('fitInside empurra a forma de volta pro quadro e recusa a que não cabe', () => {
    const out = S.fitInside([[-10, 20], [50, 20], [50, 80]], W, H);
    expect(out?.dx).toBe(10);
    expect(out?.points.every(([x]) => x >= 0)).toBe(true);
    expect(S.fitInside([[0, 0], [W + 50, 0], [0, 10]], W, H)).toBeNull();
  });

  it('wrapDeg', () => {
    expect(S.wrapDeg(190)).toBe(-170);
    expect(S.wrapDeg(-190)).toBe(170);
    expect(S.wrapDeg(180)).toBe(-180);
    expect(S.wrapDeg(45)).toBe(45);
  });

  it('lado do meio muda só a largura ou só a altura, mesmo girado', () => {
    const obb = { cx: 300, cy: 200, w: 100, h: 60, angle: S.deg2rad(30) };
    const out = S.rot(50 + 40, 0, obb.angle);
    const r = S.resizeFromEdge(obb, 1, [obb.cx + out[0], obb.cy + out[1]]);
    close(r.w, 140); close(r.h, 60);
    const left0 = S.edgeMidpoints(obb)[3], left1 = S.edgeMidpoints(r)[3];
    close(left1[0], left0[0]); close(left1[1], left0[1]);
    const up = S.rot(0, -30 - 20, obb.angle);
    const t = S.resizeFromEdge(obb, 0, [obb.cx + up[0], obb.cy + up[1]]);
    close(t.w, 100); close(t.h, 80);
  });

  it('keepRatio preserva a proporção ao arrastar o canto (quadrado continua quadrado)', () => {
    const sq = { cx: 200, cy: 200, w: 80, h: 80, angle: 0 };
    const r = S.resizeFromCorner(sq, 2, [320, 280], true);
    close(r.w, r.h, 1e-9); close(r.w, 160, 1e-9);
    const tl = S.corners(r)[0];
    close(tl[0], 160); close(tl[1], 160);
    const free = S.resizeFromCorner(sq, 2, [320, 280], false);
    close(free.w, 160); close(free.h, 120);
  });

  it('withSize troca o tamanho e mantém centro e ângulo', () => {
    const o = S.withSize({ cx: 50, cy: 60, w: 10, h: 20, angle: 1 }, 30, 40);
    expect([o.cx, o.cy, o.w, o.h, o.angle]).toEqual([50, 60, 30, 40, 1]);
  });

  it('quadrado tem lados iguais e o ícone do retângulo é mais largo que alto', () => {
    const sq = S.outline('square', { cx: 100, cy: 100, w: 60, h: 60, angle: 0 });
    close(Math.hypot(sq[1][0] - sq[0][0], sq[1][1] - sq[0][1]), Math.hypot(sq[2][0] - sq[1][0], sq[2][1] - sq[1][1]));
    const b = S.bbox(S.catalog('rect')), q = S.bbox(S.catalog('square'));
    expect(b.x1 - b.x0).toBeGreaterThan((b.y1 - b.y0) * 1.3);
    close(q.x1 - q.x0, q.y1 - q.y0, 1e-9);
  });

  it('thumbPoints encaixa a forma no ícone mantendo a proporção da imagem', () => {
    const pts = S.thumbPoints(S.catalog('square'), 16 / 9, 34, 24).split(' ').map((p) => p.split(',').map(Number));
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(0); expect(Math.max(...xs)).toBeLessThanOrEqual(34);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(0); expect(Math.max(...ys)).toBeLessThanOrEqual(24);
  });
});
