import { Component, inject, OnInit } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { IonContent, IonMenu, IonRouterOutlet, IonSplitPane, ModalController } from '@ionic/angular';

import { CamerasStore } from '../../core/cameras.store';
import { AddCameraModal } from '../cameras/add-camera.modal';
import { PwaService } from '../../core/pwa.service';
import { PwaBannersComponent } from '../../shared/pwa-banners.component';
import { LogsHostComponent } from '../logs/logs-host.component';

/** A casca do app: menu lateral fixo em telas largas (tablet/desktop) e recolhível no celular. */
@Component({
  selector: 'app-shell',
  imports: [IonSplitPane, IonMenu, IonContent, IonRouterOutlet, RouterLink, RouterLinkActive, LogsHostComponent, PwaBannersComponent],
  template: `
    <ion-split-pane contentId="main" when="lg">
      <ion-menu contentId="main" type="overlay">
        <ion-content>
          <div class="side">
            <div class="brand">
              <span class="logo" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
                  <circle cx="12" cy="12" r="3.5" fill="currentColor" />
                </svg>
              </span>
              <div><h1>atendeIO</h1><p class="muted small">Painel de câmeras</p></div>
            </div>

            <nav class="nav" aria-label="Seções">
              <a routerLink="/cameras" routerLinkActive="on" class="btn ghost">Câmeras</a>
              <a routerLink="/analise" routerLinkActive="on" class="btn ghost">Análise de fluxo</a>
            </nav>

            <div class="head"><h2>Minhas câmeras</h2><span class="pill">{{ cams.cameras().length }}</span></div>
            <div class="list">
              @for (c of cams.cameras(); track c.id) {
                <div class="cam" [class.active]="cams.isWatched(c.id)" role="button" tabindex="0"
                  (click)="cams.toggle(c.id)" (keydown.enter)="cams.toggle(c.id)" (keydown.space)="$event.preventDefault(); cams.toggle(c.id)">
                  <div class="top">
                    <span class="name">{{ c.name }}</span>
                    <span class="badge" [class.local]="c.kind === 'local'" [class.ip]="c.kind === 'rtsp'">{{ c.kind === 'rtsp' ? 'IP' : 'local' }}</span>
                  </div>
                  <div class="bottom">
                    <span class="muted small">{{ cams.isWatched(c.id) ? 'assistindo' : 'toque para assistir' }}</span>
                    <button class="del" type="button" title="Remover câmera" aria-label="Remover câmera {{ c.name }}"
                      (click)="$event.stopPropagation(); remove(c.id, c.name)">×</button>
                  </div>
                </div>
              } @empty {
                <div class="empty">Nenhuma câmera ainda. Cadastre uma abaixo.</div>
              }
            </div>
            <div class="add">
              <button class="btn" type="button" (click)="add('rtsp')">+ Câmera IP (RTSP)</button>
              <button class="btn" type="button" (click)="add('local')">+ Câmera local</button>
              @if (pwa.canInstall()) { <button class="btn primary" type="button" (click)="pwa.install()">Instalar app</button> }
              @if (pwa.iosHint()) { <p class="muted small ios">Para instalar no iPhone/iPad: toque em Compartilhar e depois em “Adicionar à Tela de Início”.</p> }
            </div>
          </div>
        </ion-content>
      </ion-menu>
      <div class="ion-page" id="main"><ion-router-outlet /></div>
    </ion-split-pane>
    <app-logs-host />
    <app-pwa-banners />
  `,
  styles: `
    ion-menu { --background: var(--panel); --side-width: 300px; --border: 1px solid var(--border); }
    ion-content { --background: var(--panel); }
    .side { display: flex; flex-direction: column; gap: 14px; padding: 16px 14px; min-height: 100%; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; color: var(--accent);
      background: var(--accent-soft); border: 1px solid var(--border-strong); }
    h1 { font-size: 17px; }
    .nav { display: grid; gap: 6px; }
    .nav a.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
    .head { display: flex; align-items: center; justify-content: space-between; margin-top: 4px;
      h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); } }
    .list { display: flex; flex-direction: column; gap: 8px; flex: 1; }
    .cam { padding: 11px 12px; border-radius: 12px; border: 1px solid var(--border); background: rgba(255, 255, 255, 0.02); cursor: pointer;
      display: flex; flex-direction: column; gap: 6px; min-height: 44px;
      &:hover { border-color: var(--border-strong); background: rgba(255, 255, 255, 0.04); }
      &.active { border-color: var(--accent); background: var(--accent-soft); box-shadow: 0 0 0 1px var(--accent) inset; } }
    .top, .bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .name { font-size: 14px; font-weight: 550; word-break: break-word; }
    .del { font: inherit; font-size: 18px; line-height: 1; color: var(--muted); background: none; border: none; cursor: pointer; padding: 4px 8px; border-radius: 6px;
      &:hover { color: var(--text); background: rgba(255, 255, 255, 0.08); } }
    .add { display: grid; gap: 8px; }
    .ios { margin: 0; line-height: 1.4; }
  `,
})
export class ShellPage implements OnInit {
  readonly cams = inject(CamerasStore);
  readonly pwa = inject(PwaService);
  private readonly modals = inject(ModalController);

  async ngOnInit(): Promise<void> {
    try { await this.cams.load(); } catch { /* a tela mostra a lista vazia; o 401 já redireciona */ }
  }

  async add(mode: 'rtsp' | 'local'): Promise<void> {
    const m = await this.modals.create({ component: AddCameraModal, componentProps: { mode } });
    await m.present();
  }

  async remove(id: number, name: string): Promise<void> {
    if (!confirm(`Remover a câmera "${name}"?`)) return;
    try { await this.cams.remove(id); } catch (e) { alert(e instanceof Error ? e.message : 'Não foi possível remover.'); }
  }
}
