import { Component, Input, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IonButton, IonButtons, IonContent, IonFooter, IonHeader, IonTitle, IonToolbar, ModalController } from '@ionic/angular';

import { CameraDataStore } from '../../core/camera-data.store';
import { Camera, ClassCatalog, ClassInfo } from '../../core/models';

const norm = (s: string): string => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/** Escolha dos objetos que o YOLO reconhece em uma câmera (as 80 classes, agrupadas, com busca). */
@Component({
  selector: 'app-recognition-modal',
  imports: [FormsModule, IonHeader, IonToolbar, IonTitle, IonButtons, IonButton, IonContent, IonFooter],
  template: `
    <ion-header><ion-toolbar>
      <ion-title>Objetos · {{ camera.name }}</ion-title>
      <ion-buttons slot="end"><ion-button (click)="close()">Fechar</ion-button></ion-buttons>
    </ion-toolbar></ion-header>
    <ion-content class="ion-padding">
      @if (catalog(); as cat) {
        <div class="top">
          <div class="rec-switch">
            <button class="switch" type="button" role="switch" [attr.aria-checked]="enabled()" (click)="enabled.set(!enabled()); dirty = true"><span class="knob"></span></button>
            <strong>{{ enabled() ? 'Reconhecimento ligado' : 'Reconhecimento desligado' }}</strong>
            <span class="pill">{{ selected().size }} de {{ cat.classes.length }} selecionados</span>
          </div>
          <input type="search" class="search" placeholder="Buscar objeto (ex.: copo, cadeira, laptop)" aria-label="Buscar objeto" [ngModel]="query()" (ngModelChange)="query.set($event)">
          <div class="actions">
            @for (p of cat.presets; track p.id) {
              <button class="btn mini" type="button" [title]="p.description" (click)="add(p.classes)">+ {{ p.label }}</button>
            }
            <button class="btn mini" type="button" (click)="add(allIds())">Marcar todos</button>
            <button class="btn mini" type="button" (click)="clear()">Limpar tudo</button>
          </div>
          @if (note()) { <p class="small muted">{{ note() }}</p> }
        </div>
        @for (g of groups(); track g.name) {
          <section class="group">
            <header>
              <label><input type="checkbox" [checked]="g.on === g.items.length" [indeterminate]="g.on > 0 && g.on < g.items.length" (change)="toggleGroup(g.items, $any($event.target).checked)"> <h3>{{ g.name }}</h3></label>
              <small class="muted">{{ g.on }}/{{ g.items.length }}</small>
            </header>
            <div class="grid">
              @for (c of g.items; track c.id) {
                <label class="item"><input type="checkbox" [checked]="selected().has(c.id)" (change)="toggle(c.id, $any($event.target).checked)"> <span>{{ c.label }}</span> <small class="muted">{{ c.name }}</small></label>
              }
            </div>
          </section>
        } @empty { <p class="muted small">Nenhum objeto encontrado.</p> }
      } @else if (error()) { <p class="form-err">{{ error() }}</p> } @else { <p class="muted">Carregando…</p> }
    </ion-content>
    <ion-footer><ion-toolbar class="foot">
      @if (saveError()) { <p class="form-err" role="alert">{{ saveError() }}</p> }
      <div class="row">
        <button class="btn primary" type="button" [disabled]="saving()" (click)="save()">{{ saving() ? 'Salvando…' : 'Salvar' }}</button>
        <button class="btn ghost" type="button" (click)="close()">Cancelar</button>
      </div>
    </ion-toolbar></ion-footer>
  `,
  styles: `
    .top { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
    .rec-switch { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .search { font: inherit; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border-strong); background: rgba(0,0,0,.25); color: var(--text); }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; }
    .group { margin-bottom: 16px; }
    .group header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin-bottom: 8px; }
    .group h3 { display: inline; margin: 0; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 4px; }
    .item { display: flex; gap: 8px; align-items: center; padding: 6px 4px; font-size: 14px; min-height: 36px; }
    .foot { --background: var(--panel); padding: 8px 16px; }
    .row { display: flex; gap: 8px; }
  `,
})
export class RecognitionModal implements OnInit {
  @Input({ required: true }) camera!: Camera;

  private readonly data = inject(CameraDataStore);
  private readonly modals = inject(ModalController);

  readonly catalog = signal<ClassCatalog | null>(null);
  readonly error = signal('');
  readonly saveError = signal('');
  readonly saving = signal(false);
  readonly enabled = signal(true);
  readonly selected = signal<Set<number>>(new Set());
  readonly query = signal('');
  dirty = false;

  readonly allIds = computed(() => this.catalog()?.classes.map((c) => c.id) ?? []);
  readonly groups = computed(() => {
    const cat = this.catalog();
    if (!cat) return [];
    const q = norm(this.query().trim());
    const sel = this.selected();
    const by = new Map<string, ClassInfo[]>();
    for (const c of cat.classes) {
      if (q && !norm(`${c.label} ${c.name}`).includes(q)) continue;
      by.set(c.group, [...(by.get(c.group) ?? []), c]);
    }
    return [...by].map(([name, items]) => ({ name, items, on: items.filter((i) => sel.has(i.id)).length }));
  });
  readonly note = computed(() => {
    if (!this.enabled()) return 'Com a chave desligada o YOLO não roda nesta câmera (economiza processamento). Pessoas e mesas não serão contadas.';
    if (!this.selected().size) return 'Nenhum objeto marcado: nada será reconhecido até você escolher.';
    if (!this.selected().has(0)) return 'Dica: marque “Pessoa” para contar pessoas e saber quais mesas estão ocupadas.';
    return '';
  });

  async ngOnInit(): Promise<void> {
    const id = this.camera.id;
    try {
      const [cat, rec] = await Promise.all([this.data.classCatalog(), this.data.recognition()[id] ?? this.data.loadRecognition(id)]);
      this.enabled.set(rec.enabled);
      this.selected.set(new Set(rec.classes));
      this.catalog.set(cat);
    } catch (e) { this.error.set(e instanceof Error ? e.message : 'Erro ao carregar.'); }
  }

  private mutate(fn: (s: Set<number>) => void): void {
    const next = new Set(this.selected());
    fn(next);
    this.selected.set(next);
    this.dirty = true;
  }
  toggle(id: number, on: boolean): void { this.mutate((s) => (on ? s.add(id) : s.delete(id))); }
  toggleGroup(items: ClassInfo[], on: boolean): void { this.mutate((s) => items.forEach((i) => (on ? s.add(i.id) : s.delete(i.id)))); }
  add(ids: number[]): void { this.mutate((s) => ids.forEach((i) => s.add(i))); }
  clear(): void { this.mutate((s) => s.clear()); }

  async save(): Promise<void> {
    this.saveError.set('');
    this.saving.set(true);
    try {
      await this.data.saveRecognition(this.camera.id, { enabled: this.enabled(), classes: [...this.selected()].sort((a, b) => a - b) });
      this.dirty = false;
      await this.modals.dismiss(true);
    } catch (e) { this.saveError.set(e instanceof Error ? e.message : 'Erro ao salvar.'); this.saving.set(false); }
  }

  async close(): Promise<void> {
    if (this.dirty && !confirm('Descartar as alterações?')) return;
    await this.modals.dismiss();
  }
}
