import { Component, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { ModalController } from '@ionic/angular';

import { CameraDataStore } from '../../core/camera-data.store';
import { Camera, CameraState, Zone } from '../../core/models';
import { StatesStore } from '../../core/states.store';
import { KIND_LABEL, STATUS, areaCaption, areaColor, naturalByName, noReading, readingHint } from '../../shared/area-labels';
import { thumbPoints } from '../../shared/shapes';
import { ZoneEditorModal } from '../zones/zone-editor.modal';

/** Painel "Salão": mesas e áreas da câmera em foco, pessoas na área e objetos reconhecidos. */
@Component({
  selector: 'app-hall-panel',
  templateUrl: './hall-panel.component.html',
  styleUrl: './hall-panel.component.scss',
})
export class HallPanelComponent {
  readonly camera = input.required<Camera>();

  private readonly data = inject(CameraDataStore);
  private readonly states = inject(StatesStore);
  private readonly modals = inject(ModalController);
  private readonly router = inject(Router);

  readonly state = computed<CameraState | undefined>(() => this.states.states()[this.camera().id]);
  readonly zones = computed<Zone[]>(() => this.data.zones()[this.camera().id] ?? []);
  readonly blind = computed(() => noReading(this.state()));
  readonly hint = computed(() => readingHint(this.state()));
  readonly ar = computed(() => { const s = this.state()?.size; return s && s[1] ? s[0] / s[1] : 16 / 9; });

  readonly rows = computed(() => {
    const areas = new Map((this.state()?.areas ?? []).map((a) => [a.id, a]));
    const blind = this.blind();
    const zs = [...this.zones()].sort(naturalByName);
    const ordered = [...zs.filter((z) => z.kind === 'mesa'), ...zs.filter((z) => z.kind !== 'mesa')];
    return ordered.map((z) => {
      const a = areas.get(z.id as number);
      const noRead = blind && z.kind === 'mesa';
      const color = noRead ? '#94a3b8' : areaColor(z, a, blind);
      return {
        id: z.id as number, name: z.name, color, noRead,
        thumb: thumbPoints(z.points, this.ar()),
        status: noRead ? 'Sem leitura' : z.kind === 'mesa' ? (a?.status ? STATUS[a.status].label : '—') : KIND_LABEL[z.kind],
        info: noRead ? this.hint() : areaCaption(z, a).replace(/^(Livre|A limpar) · /, ''),
        canClean: !noRead && z.kind === 'mesa' && a?.status === 'a_limpar',
      };
    });
  });

  readonly summary = computed(() => {
    const tables = this.zones().filter((z) => z.kind === 'mesa');
    if (!tables.length) return [];
    if (this.blind()) return [{ text: `Mesas sem leitura — ${this.hint()}`, color: '#94a3b8', n: null as number | null }];
    const areas = new Map((this.state()?.areas ?? []).map((a) => [a.id, a]));
    return (['livre', 'ocupada', 'a_limpar'] as const).map((k) => ({
      text: STATUS[k].label.toLowerCase(), color: STATUS[k].color,
      n: tables.filter((z) => areas.get(z.id as number)?.status === k).length as number | null,
    }));
  });

  readonly people = computed(() => {
    const st = this.state();
    const recOff = !!st && !st.recognition.enabled;
    const recNone = !!st && st.recognition.enabled && st.recognition.classes === 0;
    const has = !!st && st.people !== null && !recNone;
    return {
      has, value: has ? String(st!.people) : '–',
      label: recOff ? 'reconhecimento desligado' : recNone ? 'nenhum objeto selecionado'
        : (st?.people === 1 ? 'pessoa' : 'pessoas') + ' na área da câmera',
    };
  });

  readonly counts = computed(() => {
    const cs = this.state()?.counts ?? [];
    const max = Math.max(1, ...cs.map((c) => c.count));
    return cs.map((c) => ({ ...c, pct: (c.count / max) * 100 }));
  });

  async clean(zoneId: number): Promise<void> {
    try { await this.data.markClean(this.camera().id, zoneId); await this.states.refresh(); }
    catch (e) { alert(e instanceof Error ? e.message : 'Erro.'); }
  }

  async editZones(): Promise<void> {
    const m = await this.modals.create({ component: ZoneEditorModal, componentProps: { camera: this.camera(), size: this.state()?.size ?? null }, cssClass: 'wide-modal' });
    await m.present();
    await m.onDidDismiss();
    await this.states.refresh();
  }
}
