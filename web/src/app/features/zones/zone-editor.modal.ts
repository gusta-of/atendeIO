import { DecimalPipe } from '@angular/common';
import { Component, ElementRef, HostListener, Input, OnDestroy, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { IonButton, IonButtons, IonContent, IonHeader, IonTitle, IonToolbar, ModalController } from '@ionic/angular';

import { CameraDataStore } from '../../core/camera-data.store';
import { StreamUrlService } from '../../core/stream-url.service';
import { Camera, Point, ShapeKind, Zone, ZoneKind } from '../../core/models';
import { KIND_COLOR, KIND_LABEL } from '../../shared/area-labels';
import * as S from '../../shared/shapes';

const SHAPE_LABEL: Record<ShapeKind, string> = { rect: 'Retângulo', square: 'Quadrado', ellipse: 'Círculo', triangle: 'Triângulo', poly: 'Polígono' };
type ToolId = 'select' | 'rect' | 'square' | 'ellipse' | 'triangle' | 'poly';
interface Tool { id: ToolId; label: string; key: string; hint: string; icon: string | null; }
const TOOLS: Tool[] = [
  { id: 'select', label: 'Selecionar', key: 'V', hint: 'Mover, redimensionar e girar áreas', icon: null },
  { id: 'rect', label: 'Retângulo', key: 'R', hint: 'Arraste sobre o vídeo', icon: thumb('rect') },
  { id: 'square', label: 'Quadrado', key: 'Q', hint: 'Arraste sobre o vídeo (os lados ficam sempre iguais)', icon: thumb('square') },
  { id: 'ellipse', label: 'Círculo', key: 'C', hint: 'Arraste sobre o vídeo (vira elipse se não for quadrado)', icon: thumb('ellipse') },
  { id: 'triangle', label: 'Triângulo', key: 'T', hint: 'Arraste sobre o vídeo', icon: thumb('triangle') },
  { id: 'poly', label: 'Polígono', key: 'P', hint: 'Clique nos cantos; clique no 1º ponto, duplo clique ou Enter para fechar', icon: thumb('poly') },
];
function thumb(shape: ShapeKind): string { return S.thumbPoints(S.catalog(shape), 1, 22, 18); }

const PRIMITIVES = new Set<ShapeKind>(['rect', 'square', 'ellipse', 'triangle']);
const MIN_PX = 14;          // forma menor que isso é clique perdido, não uma mesa
const CLOSE_DIST_PX = 12;   // clicar perto do 1º ponto fecha o polígono
const SNAP_DEG = 15;
const DEFAULT_MARGIN = 0.06;   // sombra de assentos: 6% da altura da imagem
const MAX_MARGIN = 0.25;
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
const fmt = (pts: Point[]): string => pts.map((p) => `${p[0]},${p[1]}`).join(' ');

type Draft =
  | { type: 'drag'; shape: ShapeKind; x0: number; y0: number; x1: number; y1: number }
  | { type: 'poly'; pts: Point[]; hover: Point | null };

type Drag =
  | { type: 'draw' }
  | { type: 'move'; last: Point }
  | { type: 'rotate'; center: Point; startPtr: number; startAngle: number }
  | { type: 'corner'; index: number; obb: S.Obb }
  | { type: 'edge'; index: number; obb: S.Obb }
  | { type: 'vertex'; vi: number };

/**
 * Editor de áreas do salão: retângulo, quadrado, círculo, triângulo e polígono livre, com mover, redimensionar
 * (alças), girar (alça, campo ou teclas [ e ]) e sombra de assentos. Matemática em `shared/shapes.ts` (testada).
 * Coordenadas salvas SEMPRE normalizadas (0..1); a edição acontece em pixels do quadro.
 */
@Component({
  selector: 'app-zone-editor-modal',
  imports: [IonHeader, IonToolbar, IonTitle, IonButtons, IonButton, IonContent, DecimalPipe],
  templateUrl: './zone-editor.modal.html',
  styleUrl: './zone-editor.modal.scss',
})
export class ZoneEditorModal implements OnInit, OnDestroy {
  /** O Ionic entrega as componentProps atribuindo na instância: precisa ser @Input comum (não signal). */
  @Input({ required: true }) camera!: Camera;
  @Input() size: [number, number] | null = null;

  private readonly data = inject(CameraDataStore);
  private readonly urls = inject(StreamUrlService);
  private readonly modals = inject(ModalController);
  private readonly stage = viewChild.required<ElementRef<HTMLElement>>('stage');
  private readonly overlay = viewChild.required<ElementRef<SVGSVGElement>>('overlay');

  readonly tools = TOOLS;
  readonly kinds = Object.entries(KIND_LABEL) as [ZoneKind, string][];
  readonly maxMargin = MAX_MARGIN * 100;
  readonly shapeLabel = SHAPE_LABEL;
  readonly kindLabel = KIND_LABEL;
  readonly previewPoints = computed(() => { const z = this.selected(); return z ? S.thumbPoints(z.points, this.ar(), 64, 46) : ''; });
  color(z: Zone): string { return KIND_COLOR[z.kind]; }

  readonly list = signal<Zone[]>([]);
  readonly sel = signal<number | null>(null);
  readonly tool = signal<ToolId>('select');
  readonly draft = signal<Draft | null>(null);
  readonly frame = signal({ w: 0, h: 0 });
  readonly ar = signal(16 / 9);
  readonly natural = signal<[number, number] | null>(null);
  readonly src = signal<string | null>(null);
  readonly lock = signal(false);
  readonly saving = signal(false);
  readonly error = signal('');
  private drag: Drag | null = null;
  private dirty = false;
  private ro?: ResizeObserver;

  private readonly W = computed(() => this.frame().w || 1);
  private readonly H = computed(() => this.frame().h || 1);
  readonly selected = computed<Zone | null>(() => { const i = this.sel(); return i === null ? null : this.list()[i] ?? null; });
  readonly isPrim = computed(() => { const z = this.selected(); return !!z && PRIMITIVES.has(z.shape); });
  readonly hint = computed(() => {
    const t = this.tool();
    if (t === 'select') {
      return this.selected()
        ? 'Arraste para mover. Cantos redimensionam (Shift mantém a proporção), quadradinhos dos lados mudam só a largura ou só a altura, a bolinha de cima gira.'
        : 'Clique numa área para editar.';
    }
    return `${TOOLS.find((x) => x.id === t)!.hint}. Esc cancela.`;
  });

  /** Nomes vazios ou repetidos impedem salvar (o servidor também recusa). */
  private readonly dupCount = computed(() => {
    const seen = new Map<string, number>();
    for (const z of this.list()) { const k = z.name.trim().toLowerCase(); seen.set(k, (seen.get(k) ?? 0) + 1); }
    return seen;
  });
  readonly invalid = computed(() => this.list().some((z) => this.bad(z)));
  bad(z: Zone): boolean { const k = z.name.trim().toLowerCase(); return !k || (this.dupCount().get(k) ?? 0) > 1; }

  readonly items = computed(() => this.list().map((z, i) => ({
    i, z, thumb: S.thumbPoints(z.points, this.ar(), 34, 24), color: KIND_COLOR[z.kind], bad: this.bad(z),
  })));

  readonly shapes = computed(() => {
    const W = this.W(), H = this.H(), selIdx = this.sel();
    return this.list().map((z, i) => {
      const pts = S.toPx(z.points, W, H);
      const b = S.bbox(pts);
      return {
        i, color: KIND_COLOR[z.kind], on: i === selIdx, points: fmt(pts),
        halo: z.kind === 'mesa' && z.margin > 0 ? 2 * z.margin * H : 0,
        lx: (b.x0 + b.x1) / 2, ly: (b.y0 + b.y1) / 2, label: z.name || '(sem nome)',
      };
    });
  });

  readonly handles = computed(() => {
    const z = this.selected();
    if (!z || this.tool() !== 'select') return null;
    const W = this.W(), H = this.H();
    const pts = S.toPx(z.points, W, H);
    let pivot: Point, at: Point;
    const edges: { x: number; y: number; i: number; deg: number }[] = [];
    const corners: { x: number; y: number; i: number }[] = [];
    const verts: { x: number; y: number; i: number }[] = [];
    if (PRIMITIVES.has(z.shape)) {
      const obb = S.obbFromPoints(z.points, z.angle, W, H);
      if (z.shape !== 'square') S.edgeMidpoints(obb).forEach((c, i) => edges.push({ x: c[0], y: c[1], i, deg: S.rad2deg(obb.angle) }));
      S.corners(obb).forEach((c, i) => corners.push({ x: c[0], y: c[1], i }));
      at = S.rotateHandle(obb, 28);
      const top = S.rot(0, -obb.h / 2, obb.angle);
      pivot = [obb.cx + top[0], obb.cy + top[1]];
    } else {
      pts.forEach((p, i) => verts.push({ x: p[0], y: p[1], i }));
      const b = S.bbox(pts);
      pivot = [(b.x0 + b.x1) / 2, b.y0];
      at = [pivot[0], Math.max(12, pivot[1] - 28)];
    }
    at = [clamp(at[0], 10, W - 10), clamp(at[1], 10, H - 10)];
    return { edges, corners, verts, pivot, at };
  });

  readonly draftView = computed(() => {
    const d = this.draft();
    if (!d) return null;
    if (d.type === 'drag') {
      if (!PRIMITIVES.has(d.shape)) return null;
      return { kind: 'shape' as const, points: fmt(S.outline(d.shape, S.obbFromDrag(d.x0, d.y0, d.x1, d.y1))) };
    }
    const pts = d.hover ? [...d.pts, d.hover] : d.pts;
    return { kind: 'poly' as const, line: fmt(pts), dots: d.pts.map((p, i) => ({ x: p[0], y: p[1], r: i === 0 && d.pts.length >= 3 ? 9 : 4 })) };
  });

  /** Tamanho real do vídeo: os campos de largura/altura usam estes pixels (estáveis ao redimensionar a janela). */
  private vw(): number { return this.natural()?.[0] || this.size?.[0] || this.W(); }
  private vh(): number { return this.natural()?.[1] || this.size?.[1] || this.H(); }
  readonly sizeW = computed(() => { const z = this.selected(); if (!z || !PRIMITIVES.has(z.shape)) return 0; return Math.round((S.obbFromPoints(z.points, z.angle, this.W(), this.H()).w * this.vw()) / this.W()); });
  readonly sizeH = computed(() => { const z = this.selected(); if (!z || !PRIMITIVES.has(z.shape)) return 0; return Math.round((S.obbFromPoints(z.points, z.angle, this.W(), this.H()).h * this.vh()) / this.H()); });
  readonly seatPct = computed(() => Math.round((this.selected()?.margin ?? 0) * 100));

  ngOnInit(): void {
    this.list.set((this.data.zones()[this.camera.id] ?? []).map((z) => ({
      ...z, shape: z.shape || 'poly', angle: z.angle || 0, margin: z.margin ?? (z.kind === 'mesa' ? DEFAULT_MARGIN : 0),
      points: z.points.map((p): Point => [p[0], p[1]]),
    })));
    if (this.size && this.size[0] && this.size[1]) this.ar.set(this.size[0] / this.size[1]);
    // vídeo limpo (o editor desenha as formas): sem caixas nem áreas
    void this.urls.stream(this.camera.id, false, false).then((u) => this.src.set(u)).catch(() => undefined);
    queueMicrotask(() => {
      const el = this.stage().nativeElement;
      this.ro = new ResizeObserver(() => this.fit());
      this.ro.observe(el);
      this.fit();
    });
  }

  ngOnDestroy(): void { this.ro?.disconnect(); this.src.set(null); }

  private fit(): void {
    const el = this.stage().nativeElement;
    // área ÚTIL do palco: sem o padding (senão o quadro passa por baixo do painel lateral)
    const cs = getComputedStyle(el);
    const cw = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const ch = el.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    if (!(cw > 0) || !(ch > 0)) return;
    const w = Math.floor(Math.min(cw, ch * this.ar()));
    this.frame.set({ w, h: Math.floor(w / this.ar()) });
  }

  onLoad(ev: Event): void {
    const img = ev.target as HTMLImageElement;
    if (img.naturalWidth && img.naturalHeight) {
      this.natural.set([img.naturalWidth, img.naturalHeight]);
      this.ar.set(img.naturalWidth / img.naturalHeight);
      this.fit();
    }
  }

  // ── edição de dados ───────────────────────────────────────────────────────────────────────
  private patch(i: number, p: Partial<Zone>): void {
    this.list.update((l) => l.map((z, k) => (k === i ? { ...z, ...p } : z)));
    this.dirty = true;
  }
  private patchSel(p: Partial<Zone>): void { const i = this.sel(); if (i !== null) this.patch(i, p); }

  /** Aplica pontos (px) à zona; garante que ficam dentro do quadro. Devolve false se não couber. */
  private setPixels(i: number, pts: Point[], extra: Partial<Zone> = {}): boolean {
    const fitted = S.fitInside(pts, this.W(), this.H());
    if (!fitted) return false;
    this.patch(i, { points: S.toNorm(fitted.points, this.W(), this.H()), ...extra });
    return true;
  }

  private px(z: Zone): Point[] { return S.toPx(z.points, this.W(), this.H()); }
  private obbOf(z: Zone): S.Obb { return S.obbFromPoints(z.points, z.angle, this.W(), this.H()); }

  setTool(t: ToolId): void {
    this.tool.set(t);
    this.draft.set(null);
    this.drag = null;
    if (t !== 'select') this.sel.set(null);
  }

  select(i: number | null): void { this.sel.set(i); }

  pick(i: number): void { this.setTool('select'); this.select(i); }

  setName(v: string): void { this.patchSel({ name: v }); }
  setKind(v: string): void {
    const kind = v as ZoneKind;
    const z = this.selected();
    this.patchSel({ kind, margin: kind === 'mesa' && !z?.margin ? DEFAULT_MARGIN : (z?.margin ?? 0) });
  }
  setSeat(v: string): void {
    const n = Number(v);
    if (Number.isFinite(n)) this.patchSel({ margin: clamp(n, 0, this.maxMargin) / 100 });
  }

  remove(): void {
    const i = this.sel();
    if (i === null) return;
    this.list.update((l) => l.filter((_, k) => k !== i));
    this.sel.set(null);
    this.dirty = true;
  }

  private autoName(kind: ZoneKind): string {
    const base = KIND_LABEL[kind];
    const used = new Set(this.list().map((z) => z.name.trim().toLowerCase()));
    if (kind !== 'mesa' && !used.has(base.toLowerCase())) return base;
    for (let n = 1; ; n++) if (!used.has(`${base} ${n}`.toLowerCase())) return `${base} ${n}`;
  }

  private addZone(shape: ShapeKind, pointsPx: Point[]): void {
    const z: Zone = { id: null, name: this.autoName('mesa'), kind: 'mesa', shape, angle: 0, margin: DEFAULT_MARGIN, points: S.toNorm(pointsPx, this.W(), this.H()) };
    this.list.update((l) => [...l, z]);
    this.dirty = true;
    this.setTool('select');
    this.select(this.list().length - 1);
    setTimeout(() => { const n = document.getElementById('ed-name') as HTMLInputElement | null; n?.focus(); n?.select(); });
  }

  private finishPoly(): void {
    const d = this.draft();
    if (!d || d.type !== 'poly') return;
    const pts: Point[] = [];
    for (const p of d.pts) {   // um duplo clique registra o último ponto duas vezes
      const last = pts[pts.length - 1];
      if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 4) pts.push(p);
    }
    this.draft.set(null);
    if (pts.length >= 3) this.addZone('poly', pts);
  }

  /** Rotação (valor absoluto em graus; o Shift trava em passos). */
  rotateTo(i: number, targetDeg: number): boolean {
    const z = this.list()[i];
    targetDeg = S.wrapDeg(targetDeg);
    if (PRIMITIVES.has(z.shape)) {
      const o = this.obbOf(z);
      return this.setPixels(i, S.outline(z.shape, { ...o, angle: S.deg2rad(targetDeg) }), { angle: targetDeg });
    }
    const pts = this.px(z);
    const b = S.bbox(pts);
    return this.setPixels(i, S.rotatePoints(pts, [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2], S.deg2rad(targetDeg - z.angle)), { angle: targetDeg });
  }

  setAngle(v: string | number): void {
    const i = this.sel();
    const n = Number(v);
    if (i === null || !Number.isFinite(n)) return;
    this.rotateTo(i, clamp(n, -180, 180));
  }

  /** Largura/altura digitadas (px do vídeo). Quadrado e "manter proporção" ligam os dois campos. */
  applySize(changed: 'w' | 'h', wRaw: string | number, hRaw: string | number): void {
    const i = this.sel();
    const z = this.selected();
    if (i === null || !z || !PRIMITIVES.has(z.shape)) return;
    const kx = this.W() / this.vw(), ky = this.H() / this.vh();
    let wv = Number(wRaw), hv = Number(hRaw);
    if (!(wv > 0) || !(hv > 0)) return;
    const o = this.obbOf(z);
    const ratio = o.w / o.h;
    if (z.shape === 'square') hv = wv;
    else if (this.lock()) { if (changed === 'w') hv = wv / ratio; else wv = hv * ratio; }
    const next = S.withSize(o, Math.max(MIN_PX, wv * kx), Math.max(MIN_PX, hv * ky));
    if (!this.setPixels(i, S.outline(z.shape, next))) alert('A forma não cabe na imagem com esse tamanho.');
  }

  // ── ponteiro ──────────────────────────────────────────────────────────────────────────────
  /** Ponteiro em pixels do quadro, preso dentro da imagem. */
  private ptr(ev: PointerEvent | MouseEvent): Point {
    const r = this.overlay().nativeElement.getBoundingClientRect();
    return [clamp((ev.clientX - r.left) / r.width, 0, 1) * this.W(), clamp((ev.clientY - r.top) / r.height, 0, 1) * this.H()];
  }

  down(ev: PointerEvent): void {
    if (ev.button !== 0) return;
    const p = this.ptr(ev);
    const tgt = ev.target as SVGElement;
    const tool = this.tool();
    const svg = this.overlay().nativeElement;
    const i = this.sel();
    if (tool === 'select') {
      const handle = tgt.dataset?.['h'];
      const zi = tgt.dataset?.['zi'];
      const z = this.selected();
      if (handle && z && i !== null) {
        if (handle === 'rot') {
          const center = this.rotationCenter(z);
          this.drag = { type: 'rotate', center, startPtr: S.angleToward(center, p), startAngle: z.angle };
        } else if (handle[0] === 'c') this.drag = { type: 'corner', index: Number(handle.slice(1)), obb: this.obbOf(z) };
        else if (handle[0] === 'e') this.drag = { type: 'edge', index: Number(handle.slice(1)), obb: this.obbOf(z) };
        else this.drag = { type: 'vertex', vi: Number(handle.slice(1)) };
      } else if (zi !== undefined) {
        const n = Number(zi);
        if (n !== i) this.select(n);
        this.drag = { type: 'move', last: p };
      } else { this.select(null); return; }
      svg.setPointerCapture(ev.pointerId);
    } else if (PRIMITIVES.has(tool as ShapeKind)) {
      this.draft.set({ type: 'drag', shape: tool as ShapeKind, x0: p[0], y0: p[1], x1: p[0], y1: p[1] });
      this.drag = { type: 'draw' };
      svg.setPointerCapture(ev.pointerId);
    } else if (tool === 'poly') {
      const d = this.draft();
      const cur: Extract<Draft, { type: 'poly' }> = d && d.type === 'poly' ? d : { type: 'poly', pts: [], hover: null };
      const first = cur.pts[0];
      if (first && cur.pts.length >= 3 && Math.hypot(p[0] - first[0], p[1] - first[1]) <= CLOSE_DIST_PX) {
        this.draft.set(cur);
        this.finishPoly();
        return;
      }
      this.draft.set({ ...cur, pts: [...cur.pts, p] });
    }
  }

  private rotationCenter(z: Zone): Point {
    if (PRIMITIVES.has(z.shape)) { const o = this.obbOf(z); return [o.cx, o.cy]; }
    const b = S.bbox(this.px(z));
    return [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
  }

  move(ev: PointerEvent): void {
    const p = this.ptr(ev);
    const d = this.draft();
    if (d && d.type === 'poly') { this.draft.set({ ...d, hover: p }); return; }
    const drag = this.drag;
    const i = this.sel();
    if (!drag) return;
    if (drag.type === 'draw' && d && d.type === 'drag') {
      let x1 = p[0], y1 = p[1];
      if (d.shape === 'square' || (ev.shiftKey && d.shape !== 'triangle')) {   // lados iguais
        const s = Math.max(Math.abs(p[0] - d.x0), Math.abs(p[1] - d.y0));
        x1 = d.x0 + Math.sign(p[0] - d.x0 || 1) * s;
        y1 = d.y0 + Math.sign(p[1] - d.y0 || 1) * s;
      }
      this.draft.set({ ...d, x1, y1 });
      return;
    }
    const z = this.selected();
    if (i === null || !z) return;
    if (drag.type === 'move') {
      const pts = this.px(z);
      const b = S.bbox(pts);
      const dx = clamp(p[0] - drag.last[0], -b.x0, this.W() - b.x1);   // não sai da imagem
      const dy = clamp(p[1] - drag.last[1], -b.y0, this.H() - b.y1);
      this.setPixels(i, pts.map(([x, y]): Point => [x + dx, y + dy]));
      drag.last = [drag.last[0] + dx, drag.last[1] + dy];
    } else if (drag.type === 'corner') {
      const keep = ev.shiftKey || z.shape === 'square' || this.lock();
      const o = S.resizeFromCorner(drag.obb, drag.index, p, keep);
      if (o.w >= MIN_PX && o.h >= MIN_PX) this.setPixels(i, S.outline(z.shape, o));
    } else if (drag.type === 'edge') {
      const o = S.resizeFromEdge(drag.obb, drag.index, p);
      if (o.w >= MIN_PX && o.h >= MIN_PX) this.setPixels(i, S.outline(z.shape, o));
    } else if (drag.type === 'vertex') {
      const pts = this.px(z);
      pts[drag.vi] = p;
      this.setPixels(i, pts);
    } else if (drag.type === 'rotate') {
      let deg = drag.startAngle + S.rad2deg(S.angleToward(drag.center, p) - drag.startPtr);
      if (ev.shiftKey) deg = Math.round(deg / SNAP_DEG) * SNAP_DEG;
      this.rotateTo(i, deg);
    }
  }

  up(): void {
    const drag = this.drag;
    const d = this.draft();
    this.drag = null;
    if (drag?.type === 'draw' && d && d.type === 'drag') {
      this.draft.set(null);
      if (Math.abs(d.x1 - d.x0) >= MIN_PX && Math.abs(d.y1 - d.y0) >= MIN_PX) {
        this.addZone(d.shape, S.outline(d.shape, S.obbFromDrag(d.x0, d.y0, d.x1, d.y1)));
      }
    }
  }

  dbl(ev: MouseEvent): void { ev.preventDefault(); this.finishPoly(); }

  // ── teclado ───────────────────────────────────────────────────────────────────────────────
  @HostListener('document:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    const tag = document.activeElement?.tagName ?? '';
    const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(tag);
    const d = this.draft();
    const i = this.sel();
    if (ev.key === 'Escape') {
      if (d) { this.draft.set(null); this.drag = null; }
      else if (i !== null) this.select(null);
      else void this.close();
    } else if (ev.key === 'Enter' && d?.type === 'poly') {
      this.finishPoly();
    } else if (ev.key === 'Backspace' && d?.type === 'poly' && !typing) {
      ev.preventDefault();
      this.draft.set({ ...d, pts: d.pts.slice(0, -1) });
    } else if ((ev.key === 'Delete' || ev.key === 'Backspace') && i !== null && !typing) {
      ev.preventDefault();
      this.remove();
    } else if ((ev.key === '[' || ev.key === ']') && i !== null && !typing) {
      ev.preventDefault();
      this.setAngle(this.list()[i].angle + (ev.key === ']' ? 1 : -1) * (ev.shiftKey ? SNAP_DEG : 5));
    } else if (!typing && !ev.ctrlKey && !ev.metaKey) {
      const t = TOOLS.find((x) => x.key.toLowerCase() === ev.key.toLowerCase());
      if (t) this.setTool(t.id);
    }
  }

  // ── salvar / fechar ───────────────────────────────────────────────────────────────────────
  async save(): Promise<void> {
    this.error.set('');
    this.saving.set(true);
    try {
      await this.data.saveZones(this.camera.id, this.list().map((z) => ({
        id: z.id, name: z.name.trim(), kind: z.kind, shape: z.shape, angle: z.angle,
        margin: z.kind === 'mesa' ? z.margin : 0, points: z.points,
      })));
      this.dirty = false;
      await this.modals.dismiss(true);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : 'Erro ao salvar.');
      this.saving.set(false);
    }
  }

  async close(): Promise<void> {
    if (this.dirty && !confirm('Descartar as alterações nas áreas?')) return;
    await this.modals.dismiss();
  }
}
