import { Component, DestroyRef, ElementRef, OnInit, computed, inject, input, signal, viewChild } from '@angular/core';

import { AppConfig } from '../../core/app-config';
import { AuthService } from '../../core/auth.service';
import { Camera } from '../../core/models';
import { StreamUrlService } from '../../core/stream-url.service';
import { readPref, writePref } from '../../shared/prefs';
import { LogEvent, TYPES, clock, toNdjson } from './log-event';
import { LogsService } from './logs.service';

const MAX_CAPTURED = 2000;     // eventos guardados na janela (para exportar)
const ROW_H = 20;              // altura fixa da linha: é o que torna a virtualização barata
const OVERSCAN = 6;
const PAINT_MS = 250;          // 4 Hz
const RATE_WINDOW_MS = 5000;
interface Geom { x: number; y: number; w: number; h: number; }

/**
 * Janela flutuante de logs (depuração leve): o que a câmera "vê", em JSON, quase em tempo real (SSE).
 * Feita para NUNCA pesar: lista VIRTUALIZADA (só ~40 linhas no DOM), pintura em lote a 4 Hz, JSON serializado
 * UMA vez na chegada, anel de 2000 eventos, e recolhida/aba escondida => conexão fechada (custo zero).
 */
@Component({
  selector: 'app-logs-window',
  templateUrl: './logs-window.component.html',
  styleUrl: './logs-window.component.scss',
})
export class LogsWindowComponent implements OnInit {
  readonly camera = input.required<Camera>();

  private readonly urls = inject(StreamUrlService);
  private readonly logs = inject(LogsService);
  private readonly auth = inject(AuthService);
  private readonly cfg = inject(AppConfig);
  private readonly destroyRef = inject(DestroyRef);
  private readonly root = viewChild.required<ElementRef<HTMLElement>>('root');
  private readonly list = viewChild.required<ElementRef<HTMLElement>>('list');

  readonly types = TYPES;
  readonly clock = clock;
  readonly rowH = ROW_H;

  // dados "quentes" ficam fora de signals (mudam várias vezes por segundo); a tela lê num relógio de 4 Hz
  private events: LogEvent[] = [];
  private view: LogEvent[] = [];
  private lastSeq = 0;
  private throttled = 0;
  private peakPeople = 0;
  private readonly recent: number[] = [];
  private readonly startedAt = Date.now();
  private readonly filter = new Set<string>(TYPES.filter((t) => t.on).map((t) => t.id));
  private query = '';
  private detail = false;
  private es: EventSource | null = null;
  private paintTimer: ReturnType<typeof setTimeout> | null = null;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  private statsTimer: ReturnType<typeof setInterval> | null = null;
  private readonly suspended = new Set<string>();

  readonly minimized = signal(false);
  readonly paused = signal(false);
  readonly autoscroll = signal(true);
  readonly status = signal<{ kind: 'on' | 'warn' | 'off'; text: string }>({ kind: 'warn', text: 'conectando…' });
  readonly selected = signal<LogEvent | null>(null);
  readonly rows = signal<{ i: number; e: LogEvent }[]>([]);
  readonly offset = signal(0);
  readonly total = signal(0);
  readonly statsText = signal('');
  readonly flash = signal('');
  readonly typeOn = signal<Set<string>>(new Set(this.filter));
  readonly inspector = computed(() => { const e = this.selected(); return e ? JSON.stringify(e, (k, v) => (k === '_s' || k === '_l' ? undefined : v), 2) : ''; });

  geom = signal<Geom>({ x: 0, y: 0, w: 560, h: 440 });
  z = computed(() => 40 + (this.logs.front() === this.camera().id ? 5 : 0));

  ngOnInit(): void {
    const n = this.logs.windows().length - 1;
    const saved = readPref<Geom | null>(`logwin.${this.camera().id}`, null);
    this.geom.set(saved ?? { w: 560, h: 440, x: Math.max(12, innerWidth - 580 - n * 28), y: Math.max(12, innerHeight - 460 - n * 28) });
    const onVis = () => this.sync();
    document.addEventListener('visibilitychange', onVis);
    this.statsTimer = setInterval(() => this.paintStats(), 1000);   // eventos/s e tempo continuam andando sem evento novo
    const ro = new ResizeObserver(() => { this.dirty(); });
    queueMicrotask(() => ro.observe(this.root().nativeElement));
    this.destroyRef.onDestroy(() => {
      document.removeEventListener('visibilitychange', onVis);
      ro.disconnect();
      this.disconnect();
      for (const t of [this.paintTimer, this.searchTimer]) if (t) clearTimeout(t);
      if (this.statsTimer) clearInterval(this.statsTimer);
      this.saveGeom();
    });
    this.paintStats();
    this.sync();
  }

  // ── filtro e pintura virtualizada ───────────────────────────────────────────────────────────
  private matches(e: LogEvent): boolean {
    return this.filter.has(e.type) && (!this.query || (e._l ??= `${e.event} ${e.type} ${e._s}`.toLowerCase()).includes(this.query));
  }
  private refilter(): void { this.view = this.events.filter((e) => this.matches(e)); this.dirty(); }
  private dirty(): void { if (!this.paintTimer && !this.paused()) this.paintTimer = setTimeout(() => this.paint(), PAINT_MS); }

  private paint(): void {
    this.paintTimer = null;
    if (this.suspended.size) return;
    const list = this.list().nativeElement;
    this.total.set(this.view.length);
    if (this.autoscroll()) list.scrollTop = this.view.length * ROW_H;
    const first = Math.max(0, Math.floor(list.scrollTop / ROW_H) - OVERSCAN);
    const count = Math.max(0, Math.min(this.view.length - first, Math.ceil(list.clientHeight / ROW_H) + OVERSCAN * 2));
    this.offset.set(first * ROW_H);
    this.rows.set(this.view.slice(first, first + count).map((e, k) => ({ i: first + k, e })));
    this.paintStats();
  }

  onScroll(): void {
    const l = this.list().nativeElement;
    const atBottom = l.scrollHeight - l.scrollTop - l.clientHeight < ROW_H * 1.5;
    if (!atBottom && this.autoscroll()) this.autoscroll.set(false);
    this.dirty();
  }

  pick(e: LogEvent): void { this.selected.set(this.selected() === e ? null : e); this.dirty(); }

  private paintStats(): void {
    const now = Date.now();
    while (this.recent.length && now - this.recent[0] > RATE_WINDOW_MS) this.recent.shift();
    const rate = (this.recent.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
    this.statsText.set(`${this.events.length} capturados · ${rate}/s · pico de pessoas ${this.peakPeople} · ${Math.round((now - this.startedAt) / 1000)}s`
      + (this.throttled ? ` · ${this.throttled} cortados pelo servidor` : '') + (this.paused() ? ' · em pausa' : ''));
  }

  // ── ações ─────────────────────────────────────────────────────────────────────────────────
  togglePause(): void { this.paused.update((p) => !p); if (!this.paused()) this.refilter(); this.paintStats(); }
  clear(): void { this.events = []; this.view = []; this.selected.set(null); this.throttled = 0; this.peakPeople = 0; this.dirty(); this.paintStats(); }
  setAuto(on: boolean): void { this.autoscroll.set(on); if (on) this.dirty(); }
  setQuery(v: string): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => { this.query = v.trim().toLowerCase(); this.refilter(); }, 200);
  }
  setType(id: string, on: boolean): void {
    if (on) this.filter.add(id); else this.filter.delete(id);
    this.typeOn.set(new Set(this.filter));
    if (id === 'frame') this.connect(on);   // o detalhe por quadro só existe no servidor enquanto alguém pede
    this.refilter();
  }

  private blink(text: string): void { this.flash.set(text); setTimeout(() => this.flash.set(''), 1200); }

  async copy(): Promise<void> {
    try { await navigator.clipboard.writeText(toNdjson(this.view.slice(-500))); this.blink('Copiado!'); }
    catch { this.blink('Sem permissão'); }
  }

  save(): void {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const url = URL.createObjectURL(new Blob([toNdjson(this.events)], { type: 'application/x-ndjson' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `atendeio-camera-${this.camera().id}-${stamp}.ndjson`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  toggleMin(): void { this.minimized.update((m) => !m); this.sync(); }
  close(): void { this.logs.close(this.camera().id); }
  raise(): void { this.logs.front.set(this.camera().id); }

  // ── conexão SSE (só existe com a janela visível) ────────────────────────────────────────────
  private ingest(raw: string): void {
    let e: LogEvent;
    try { e = JSON.parse(raw) as LogEvent; } catch { return; }
    if (e.seq) { if (e.seq <= this.lastSeq) return; this.lastSeq = e.seq; }   // já tinha (reconexão / troca de detalhe)
    e._s = JSON.stringify(e.data);                                              // serializa UMA vez; linha e busca usam este texto
    if (e.event === 'events.throttled') this.throttled += Number(e.data['count'] ?? 0);
    this.events.push(e);
    if (this.events.length > MAX_CAPTURED + 200) this.events = this.events.slice(-MAX_CAPTURED);
    this.recent.push(Date.now());
    const p = e.type === 'snapshot' ? e.data['people'] : e.event === 'people.changed' ? e.data['to'] : null;
    if (typeof p === 'number' && p > this.peakPeople) this.peakPeople = p;
    if (this.matches(e)) {
      this.view.push(e);
      if (this.view.length > MAX_CAPTURED + 200) this.view = this.view.slice(-MAX_CAPTURED);
      this.dirty();
    }
  }

  private connectSeq = 0;

  private connect(withDetail: boolean): void {
    this.detail = withDetail;
    this.disconnect();
    if (this.suspended.size) return;
    const mine = ++this.connectSeq;
    // no app nativo a URL leva um tíquete novo a cada conexão (ele vale poucos segundos)
    this.urls.events(this.camera().id, this.detail).then((url) => {
      if (mine === this.connectSeq && !this.suspended.size) this.open(url);
    }).catch(() => this.status.set({ kind: 'off', text: 'sem conexão' }));
  }

  private open(url: string): void {
    this.disconnect();
    const es = new EventSource(url);
    this.es = es;
    es.onopen = () => this.status.set({ kind: 'on', text: this.detail ? 'ao vivo · quadros' : 'ao vivo' });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) void this.explain();   // o navegador desistiu (ex.: 401/404/429)
      else this.status.set({ kind: 'warn', text: 'reconectando…' });
      if (this.cfg.token()) { this.disconnect(); setTimeout(() => this.connect(this.detail), 3000); }   // tíquete vencido: pede outro
    };
    for (const t of TYPES) es.addEventListener(t.id, (m) => this.ingest((m as MessageEvent<string>).data));
  }

  private disconnect(): void { this.connectSeq++; this.es?.close(); this.es = null; }

  /** Recolhida ou aba escondida => desconecta (a câmera nem precisa montar eventos para esta janela). */
  private sync(): void {
    this.suspended.clear();
    if (this.minimized()) this.suspended.add('min');
    if (document.hidden) this.suspended.add('hidden');
    if (this.suspended.size) {
      this.disconnect();
      this.status.set({ kind: 'off', text: this.minimized() ? 'recolhida (desconectada)' : 'aba em segundo plano (desconectada)' });
    } else { this.connect(this.detail); this.dirty(); }
  }

  private async explain(): Promise<void> {
    const status = await this.urls.probe(await this.urls.events(this.camera().id, false));
    if (status === 401) { this.auth.expire(); return; }
    const text: Record<number, string> = { 404: 'câmera não encontrada', 429: 'limite de câmeras simultâneas' };
    this.status.set({ kind: 'off', text: text[status] ?? 'sem conexão' });
  }

  // ── janela: arrastar pelo cabeçalho; tamanho pelo resize do CSS ───────────────────────────────
  private saveGeom(): void {
    const r = this.root().nativeElement.getBoundingClientRect();
    if (!r.width) return;
    const g = { x: r.left, y: r.top, w: r.width, h: r.height };
    this.geom.set(g);
    writePref(`logwin.${this.camera().id}`, g);
  }

  startDrag(ev: PointerEvent): void {
    if ((ev.target as HTMLElement).closest('button')) return;
    const el = this.root().nativeElement;
    const head = ev.currentTarget as HTMLElement;
    const r = el.getBoundingClientRect();
    const dx = ev.clientX - r.left, dy = ev.clientY - r.top;
    head.setPointerCapture(ev.pointerId);
    const move = (e: PointerEvent): void => {
      el.style.left = `${Math.min(Math.max(0, e.clientX - dx), innerWidth - 80)}px`;
      el.style.top = `${Math.min(Math.max(0, e.clientY - dy), innerHeight - 40)}px`;
    };
    const up = (): void => { head.removeEventListener('pointermove', move); head.removeEventListener('pointerup', up); this.saveGeom(); };
    head.addEventListener('pointermove', move);
    head.addEventListener('pointerup', up);
  }
}
