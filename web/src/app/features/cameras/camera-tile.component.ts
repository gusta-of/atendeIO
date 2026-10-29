import { Component, DestroyRef, ElementRef, OnInit, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { ModalController } from '@ionic/angular';

import { CameraDataStore } from '../../core/camera-data.store';
import { CamerasStore } from '../../core/cameras.store';
import { Camera, CameraState, MonitorSettings, RecognitionSettings, Zone } from '../../core/models';
import { StatesStore } from '../../core/states.store';
import { StreamUrlService } from '../../core/stream-url.service';
import { areaColor, areaLabel, noReading } from '../../shared/area-labels';
import { plural } from '../../shared/format';
import { readPref, writePref } from '../../shared/prefs';
import { LogsService } from '../logs/logs.service';
import { RecognitionModal } from '../recognition/recognition.modal';
import { ZoneEditorModal } from '../zones/zone-editor.modal';

interface Tag { id: number; x: number; y: number; w: number; text: string; color: string; }

/** Uma câmera ao vivo: vídeo MJPEG (o servidor já pinta áreas e caixas), etiquetas, chips e chaves. */
@Component({
  selector: 'app-camera-tile',
  templateUrl: './camera-tile.component.html',
  styleUrl: './camera-tile.component.scss',
  host: { class: 'tile-host' },
})
export class CameraTileComponent implements OnInit {
  readonly camera = input.required<Camera>();

  private readonly cams = inject(CamerasStore);
  private readonly data = inject(CameraDataStore);
  private readonly states = inject(StatesStore);
  private readonly urls = inject(StreamUrlService);
  private readonly modals = inject(ModalController);
  private readonly router = inject(Router);
  private readonly logs = inject(LogsService);
  private readonly destroyRef = inject(DestroyRef);

  private readonly box = viewChild.required<ElementRef<HTMLElement>>('box');

  readonly view = signal({ areas: true, boxes: true });
  readonly src = signal<string | null>(null);
  readonly message = signal('');
  readonly boxSize = signal({ w: 0, h: 0 });
  readonly naturalAr = signal(16 / 9);
  private retryDelay = 1000;
  private startSeq = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  readonly state = computed<CameraState | undefined>(() => this.states.states()[this.camera().id]);
  readonly zones = computed<Zone[]>(() => this.data.zones()[this.camera().id] ?? []);
  readonly rec = computed<RecognitionSettings | undefined>(() => this.data.recognition()[this.camera().id]);
  readonly mon = computed<MonitorSettings | undefined>(() => this.data.monitor()[this.camera().id]);
  readonly blind = computed(() => noReading(this.state()));
  readonly focused = computed(() => this.cams.focus()?.id === this.camera().id && this.cams.watched().length > 1);

  readonly ar = computed(() => {
    const s = this.state()?.size;
    return s && s[1] ? s[0] / s[1] : this.naturalAr();
  });
  /** O quadro (vídeo + etiquetas) acompanha a proporção real do vídeo, centralizado na caixa. */
  readonly frame = computed(() => {
    const { w: cw, h: ch } = this.boxSize();
    if (!cw || !ch) return { w: 0, h: 0 };
    const w = Math.floor(Math.min(cw, ch * this.ar()));
    return { w, h: Math.floor(w / this.ar()) };
  });

  readonly tags = computed<Tag[]>(() => {
    if (!this.view().areas) return [];
    const { w: W, h: H } = this.frame();
    if (!W || !H) return [];
    const areas = new Map((this.state()?.areas ?? []).map((a) => [a.id, a]));
    return this.zones().filter((z) => z.id !== null).map((z) => {
      const a = areas.get(z.id as number);
      const text = areaLabel(z, a, this.blind());
      const tw = Math.ceil(text.length * 6.1) + 10;
      const minX = Math.min(...z.points.map((p) => p[0])) * W;
      const minY = Math.min(...z.points.map((p) => p[1])) * H;
      return { id: z.id as number, text, w: tw, color: areaColor(z, a, this.blind()),
        x: Math.min(Math.max(minX, 0), Math.max(0, W - tw)), y: Math.min(Math.max(minY, 0), H - 16) };
    });
  });

  readonly chips = computed(() => {
    const st = this.state();
    if (!st) return { kind: 'connecting' as const };
    if (st.recognition && !st.recognition.enabled) return { kind: 'off' as const };
    if (st.recognition && st.recognition.classes === 0) return { kind: 'none' as const };
    return { kind: 'ok' as const, people: st.people, others: st.counts.filter((c) => c.name !== 'person').slice(0, 5) };
  });

  readonly okChips = computed(() => {
    const c = this.chips();
    return c.kind === 'ok' ? c : null;
  });

  constructor() {
    effect(() => {
      // o quadro precisa remedir quando a caixa muda de tamanho
      const el = this.box().nativeElement;
      const ro = new ResizeObserver(() => this.boxSize.set({ w: el.clientWidth, h: el.clientHeight }));
      ro.observe(el);
      this.destroyRef.onDestroy(() => ro.disconnect());
    });
    const onVis = () => { if (document.hidden) this.stop(); else this.start(); };
    document.addEventListener('visibilitychange', onVis);
    this.destroyRef.onDestroy(() => { document.removeEventListener('visibilitychange', onVis); this.stop(); });
  }

  ngOnInit(): void {
    const id = this.camera().id;
    this.view.set(readPref(`view.${id}`, { areas: true, boxes: true }));
    void this.data.loadZones(id).catch(() => undefined);
    void this.data.loadRecognition(id).catch(() => undefined);
    void this.data.loadMonitor(id).catch(() => undefined);
    this.start();
  }

  plural = plural;

  // ── vídeo ─────────────────────────────────────────────────────────────────────────────────
  start(): void {
    this.clearRetry();
    const mine = ++this.startSeq;
    void this.urls.stream(this.camera().id, this.view().boxes, this.view().areas).then((u) => {
      if (mine === this.startSeq) this.src.set(u);   // ignora respostas atrasadas (troca rápida de Áreas/Caixas)
    }).catch(() => this.scheduleRetry());
  }

  stop(): void {
    this.clearRetry();
    this.startSeq++;
    this.src.set(null);   // tirar o src fecha a conexão: o servidor para de enviar
  }

  private clearRetry(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  onLoad(ev: Event): void {
    this.retryDelay = 1000;
    this.message.set('');
    const img = ev.target as HTMLImageElement;
    if (img.naturalWidth && img.naturalHeight) this.naturalAr.set(img.naturalWidth / img.naturalHeight);
  }

  /** O <img> não diz o motivo da falha: sonda o status e decide entre reconectar, avisar ou desistir. */
  async onError(): Promise<void> {
    const url = this.src();
    if (!url || document.hidden) return;
    const status = await this.urls.probe(url);
    if (status === 404) { await this.cams.load().catch(() => undefined); return; }
    if (status === 429) { this.message.set('Limite de câmeras simultâneas atingido.'); return; }
    if (status === 200) { this.start(); return; }               // era um tropeço passageiro
    this.scheduleRetry();
  }

  private scheduleRetry(): void {
    this.message.set(`Sem sinal — nova tentativa em ${Math.round(this.retryDelay / 1000)}s`);
    this.retryTimer = setTimeout(() => this.start(), this.retryDelay);
    this.retryDelay = Math.min(this.retryDelay * 2, 15000);
  }

  // ── ações ─────────────────────────────────────────────────────────────────────────────────
  setView(key: 'areas' | 'boxes'): void {
    const next = { ...this.view(), [key]: !this.view()[key] };
    this.view.set(next);
    writePref(`view.${this.camera().id}`, next);
    this.start();   // caixas e áreas vêm desenhadas no vídeo: reconecta na outra variante
  }

  focus(): void { this.cams.focusId.set(this.camera().id); }
  unwatch(): void { this.cams.toggle(this.camera().id); }

  async toggleRecognition(): Promise<void> {
    const cur = this.rec();
    if (!cur) return;
    const before = cur;
    this.data.recognition.update((m) => ({ ...m, [this.camera().id]: { ...cur, enabled: !cur.enabled } }));   // otimista
    try { await this.data.saveRecognition(this.camera().id, { enabled: !before.enabled, classes: before.classes }); await this.states.refresh(); }
    catch (e) { this.data.recognition.update((m) => ({ ...m, [this.camera().id]: before })); alert(e instanceof Error ? e.message : 'Erro.'); }
  }

  async toggleMonitor(): Promise<void> {
    const cur = this.mon();
    const next = !(cur?.enabled);
    try {
      const r = await this.data.saveMonitor(this.camera().id, next, cur?.from ?? '', cur?.to ?? '');
      if (r.enabled && confirm('Monitoramento ligado: a câmera será analisada o dia todo, mesmo com o painel fechado.\n\nQuer ver a análise de fluxo agora?')) {
        await this.router.navigate(['/analise'], { queryParams: { camera: this.camera().id } });
      }
    } catch (e) { alert(e instanceof Error ? e.message : 'Erro.'); }   // ex.: falta marcar "Pessoa" em Objetos
  }

  async openObjects(): Promise<void> {
    const m = await this.modals.create({ component: RecognitionModal, componentProps: { camera: this.camera() }, cssClass: 'wide-modal' });
    await m.present();
    await m.onDidDismiss();
    await this.states.refresh();
  }

  async editZones(): Promise<void> {
    const size = this.state()?.size ?? null;
    const m = await this.modals.create({ component: ZoneEditorModal, componentProps: { camera: this.camera(), size }, cssClass: 'wide-modal' });
    await m.present();
    await m.onDidDismiss();
    await this.states.refresh();
  }

  openLogs(): void { this.logs.open(this.camera()); }
}
