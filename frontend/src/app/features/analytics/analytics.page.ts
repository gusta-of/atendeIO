import { Component, OnInit, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IonContent } from '@ionic/angular';

import { ApiClient } from '../../core/api.service';
import { AppConfig } from '../../core/app-config';
import { CameraDataStore } from '../../core/camera-data.store';
import { CamerasStore } from '../../core/cameras.store';
import { FlowDaySeries, FlowReport, MonitorSettings } from '../../core/models';
import { brDate, hh, num, pct } from '../../shared/format';
import { readPref, writePref } from '../../shared/prefs';
import { TabbarComponent } from '../../shared/tabbar.component';
import { TopbarComponent } from '../../shared/topbar.component';
import { AnCardComponent } from './an-card.component';
import { AnTableComponent } from './an-table.component';
import { AnTipComponent } from './an-tip.component';
import { WD_SHORT, weekly } from './chart-models';
import { AreaBarsComponent, ColumnChartComponent, DayChartComponent, HeatmapComponent } from './charts.component';

type Days = number | 'custom';
const PRESETS: { label: string; days: Days }[] = [
  { label: 'Hoje', days: 0 }, { label: '7 dias', days: 6 }, { label: '30 dias', days: 29 }, { label: '90 dias', days: 89 }, { label: 'Personalizado', days: 'custom' },
];
const isoDay = (d: Date): string => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** Análise de fluxo: média e pico de pessoas, horas/dias mais cheios e vazios, mapa de calor, dia a dia e áreas. */
@Component({
  selector: 'app-analytics-page',
  imports: [IonContent, FormsModule, TopbarComponent, TabbarComponent, AnCardComponent, AnTableComponent, AnTipComponent,
    ColumnChartComponent, HeatmapComponent, DayChartComponent, AreaBarsComponent],
  templateUrl: './analytics.page.html',
  styleUrl: './analytics.page.scss',
})
export class AnalyticsPage implements OnInit {
  /** Vem de `?camera=` (ligado pelo roteador). */
  readonly camera = input<string | undefined>();

  private readonly api = inject(ApiClient);
  private readonly cfg = inject(AppConfig);
  private readonly cams = inject(CamerasStore);
  private readonly data = inject(CameraDataStore);

  readonly presets = PRESETS;
  readonly hoursFrom = Array.from({ length: 24 }, (_, i) => ({ v: i, t: hh(i) }));
  readonly hoursTo = Array.from({ length: 24 }, (_, i) => ({ v: i + 1, t: i === 23 ? '24h' : hh(i + 1) }));
  readonly num = num;
  readonly hh = hh;
  readonly brDate = brDate;
  readonly WD = WD_SHORT;

  readonly camId = signal<number | null>(null);
  readonly days = signal<Days>(readPref<Days>('an.days', 6));
  readonly from = signal('');
  readonly to = signal('');
  readonly hfrom = signal(readPref('an.hfrom', 0));
  readonly hto = signal(readPref('an.hto', 24));
  readonly dayDate = signal('');
  readonly report = signal<FlowReport | null>(null);
  readonly day = signal<FlowDaySeries | null>(null);
  readonly monitor = signal<MonitorSettings | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly monErr = signal('');
  readonly monFrom = signal('');
  readonly monTo = signal('');
  private seq = 0;
  private reportKey = '';

  readonly cameras = this.cams.cameras;
  readonly query = computed(() => {
    const p = new URLSearchParams({ hour_from: String(this.hfrom()), hour_to: String(this.hto()) });
    const d = this.days();
    if (d === 'custom') { if (this.from()) p.set('from', this.from()); if (this.to()) p.set('to', this.to()); }
    else p.set('days', String(d + 1));
    return p.toString();
  });

  // ── derivados da resposta ──────────────────────────────────────────────────────────────────
  readonly summary = computed(() => this.report()?.summary ?? null);
  readonly hasData = computed(() => (this.summary()?.samples ?? 0) > 0);
  readonly peakText = computed(() => { const p = this.summary()?.peak; return p ? `${p.weekday}, ${brDate(p.at)} às ${p.hour}h` : ''; });
  readonly hours = computed(() => {
    const r = this.report();
    return r ? r.hourly.filter((x) => x.hour >= r.range.hour_from && x.hour < r.range.hour_to) : [];
  });
  readonly hoursItems = computed(() => this.hours().map((d, i, a) => ({ avg: d.avg, max: d.max, label: hh(d.hour), x: a.length <= 12 || i % 2 === 0 ? String(d.hour) : '' })));
  readonly longRange = computed(() => (this.report()?.daily.length ?? 0) > 92);
  readonly dailyData = computed(() => { const r = this.report(); return !r ? [] : this.longRange() ? weekly(r.daily) : r.daily; });
  readonly dailyItems = computed(() => {
    const d = this.dailyData();
    const step = Math.ceil(d.length / 8);
    return d.map((x, i) => ({ avg: x.avg, max: x.max, label: `${this.longRange() ? 'Semana de ' : ''}${brDate(x.date)}`, x: i % step === 0 ? brDate(x.date) : '' }));
  });
  readonly suggest = computed(() => {
    const r = this.report();
    if (!r) return null;
    const used = r.hourly.filter((x) => x.samples > 0).map((x) => x.hour);
    if (!used.length || r.range.hour_from !== 0 || r.range.hour_to !== 24) return null;
    const lo = Math.min(...used), hi = Math.max(...used) + 1;
    return lo > 0 || hi < 24 ? { lo, hi, text: `Ver só ${hh(lo)} às ${hi === 24 ? '24h' : hh(hi)} (as horas com dados)` } : null;
  });
  readonly heatHeaders = computed(() => { const r = this.report(); return r ? ['Dia', ...Array.from({ length: r.range.hour_to - r.range.hour_from }, (_, i) => hh(r.range.hour_from + i))] : []; });
  readonly heatRows = computed(() => { const r = this.report(); return r ? r.heatmap.map((row, i) => [WD_SHORT[i], ...row.slice(r.range.hour_from, r.range.hour_to).map((v) => num(v))]) : []; });
  readonly hourRows = computed(() => this.hours().map((d) => [hh(d.hour), num(d.avg), d.max ?? '–', d.samples]));
  readonly dailyRows = computed(() => this.dailyData().map((d) => [brDate(d.date), num(d.avg), d.max, d.samples]));
  readonly dayRows = computed(() => (this.day()?.series ?? []).map((p) => [p.t, num(p.avg), p.max]));
  readonly areaRows = computed(() => (this.report()?.areas ?? []).map((a) => [a.name, a.kind, num(a.avg), a.max]));
  readonly pct = pct;

  constructor() {
    // recarrega o relatório sempre que câmera, período ou faixa de horas mudam
    effect(() => {
      const id = this.camId();
      const q = this.query();
      if (id === null) return;
      const key = `${id}?${q}`;
      untracked(() => { if (key !== this.reportKey) { this.reportKey = key; void this.loadReport(); } });
    });
  }

  async ngOnInit(): Promise<void> {
    try { if (!this.cams.loaded()) await this.cams.load(); } catch { /* a lista vazia explica */ }
    const list = this.cams.cameras();
    if (!list.length) return;
    const wanted = Number(this.camera()) || Number(readPref('an.camera', 0));
    this.chooseCamera(list.some((c) => c.id === wanted) ? wanted : list[0].id);
  }

  chooseCamera(id: number): void {
    this.camId.set(id);
    writePref('an.camera', id);
    this.dayDate.set('');
    void this.loadMonitor();
  }

  setDays(d: Days): void {
    if (d === 'custom' && !this.from()) {
      const t = new Date();
      this.to.set(isoDay(t));
      t.setDate(t.getDate() - 6);
      this.from.set(isoDay(t));
    }
    this.days.set(d);
    writePref('an.days', d);
  }

  setHours(from: number, to: number): void {
    if (to <= from) { if (from !== this.hfrom()) to = from + 1; else from = to - 1; }
    this.hfrom.set(from);
    this.hto.set(to);
    writePref('an.hfrom', from);
    writePref('an.hto', to);
  }

  // ── dados ─────────────────────────────────────────────────────────────────────────────────
  private async loadReport(): Promise<void> {
    const mine = ++this.seq, id = this.camId();
    if (id === null) return;
    this.loading.set(true);   // segura o quadro anterior em vez de piscar um esqueleto
    this.error.set('');
    try {
      const rep = await this.api.get<FlowReport>(`/api/cameras/${id}/flow?${this.query()}`);
      if (mine !== this.seq) return;   // chegou uma resposta mais nova no meio
      this.report.set(rep);
      const cur = this.dayDate();
      if (!cur || cur < rep.range.from || cur > rep.range.to) {
        const withData = rep.daily.filter((d) => d.samples > 0);
        this.dayDate.set(withData.length ? withData[withData.length - 1].date : rep.range.to);
      }
      await this.loadDay();
    } catch (e) {
      if (mine === this.seq) this.error.set(e instanceof Error ? e.message : 'Erro ao carregar.');
    } finally {
      if (mine === this.seq) this.loading.set(false);
    }
  }

  async loadDay(): Promise<void> {
    const id = this.camId();
    if (id === null || !this.dayDate()) return;
    try { this.day.set(await this.api.get<FlowDaySeries>(`/api/cameras/${id}/flow/day?date=${this.dayDate()}`)); }
    catch { this.day.set(null); }
  }

  pickDay(v: string): void { this.dayDate.set(v); void this.loadDay(); }

  /** Baixa o CSV (fetch + blob: funciona com cookie no web e com Bearer no app nativo). */
  async csv(): Promise<void> {
    const id = this.camId();
    if (id === null) return;
    try {
      const token = this.cfg.token();
      const r = await fetch(this.cfg.url(`/api/cameras/${id}/flow.csv?${this.query()}`), token ? { headers: { Authorization: `Bearer ${token}` } } : { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`Erro ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = `atendeio-fluxo-camera-${id}.csv`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { alert(e instanceof Error ? e.message : 'Não foi possível baixar.'); }
  }

  // ── monitoramento (é aqui que o histórico passa a ser gravado) ─────────────────────────────
  async loadMonitor(): Promise<void> {
    const id = this.camId();
    if (id === null) return;
    try {
      const m = await this.data.loadMonitor(id);
      this.monitor.set(m);
      this.monFrom.set(m.from);
      this.monTo.set(m.to);
      if (m.from && m.to && readPref<number | null>('an.hfrom', null) === null) {   // sem escolha do utilizador: usa o horário de funcionamento
        const f = Number(m.from.slice(0, 2)), t = Number(m.to.slice(0, 2)) + (m.to.slice(3) !== '00' ? 1 : 0) || 24;
        if (f < t) { this.hfrom.set(f); this.hto.set(Math.min(24, t)); }
      }
    } catch { this.monitor.set(null); }
  }

  async saveMonitor(enabled: boolean): Promise<void> {
    const id = this.camId();
    if (id === null) return;
    this.monErr.set('');
    try { await this.data.saveMonitor(id, enabled, this.monFrom(), this.monTo()); await this.loadMonitor(); }
    catch (e) { this.monErr.set(e instanceof Error ? e.message : 'Erro.'); }
  }

  readonly monMessage = computed(() => {
    const m = this.monitor();
    if (!m) return '';
    if (!m.enabled) return 'Monitoramento desligado: nenhum dado novo está sendo gravado para a análise.';
    return `${m.from ? `Monitorando das ${m.from} às ${m.to}.` : 'Monitorando o dia todo.'} O histórico é gravado mesmo sem ninguém olhando o vídeo.`;
  });
}
