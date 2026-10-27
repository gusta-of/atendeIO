import { Component, Input, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IonContent, IonHeader, IonTitle, IonToolbar, ModalController } from '@ionic/angular';

import { CamerasStore } from '../../core/cameras.store';
import { LocalDevice } from '../../core/models';

/** Cadastro de câmera: IP/RTSP (o servidor monta a URL a partir de IP + usuário + senha) ou câmera local do servidor. */
@Component({
  selector: 'app-add-camera',
  imports: [IonHeader, IonToolbar, IonTitle, IonContent, FormsModule],
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-title>{{ mode === 'rtsp' ? 'Câmera IP (RTSP)' : 'Câmera local' }}</ion-title>
        <button slot="end" class="btn ghost mini close" type="button" (click)="close()">Fechar</button>
      </ion-toolbar>
    </ion-header>
    <ion-content>
      <div class="body">
        @if (mode === 'rtsp') {
          <form class="form" (ngSubmit)="saveRtsp()" autocomplete="off">
            <label>Nome <input name="name" [(ngModel)]="name" maxlength="80" placeholder="ex.: Recepção" /></label>
            <label>Marca
              <select name="brand" [ngModel]="brand()" (ngModelChange)="pickBrand($event)">
                @for (p of presets(); track p.key) { <option [value]="p.key">{{ p.label }}</option> }
              </select>
            </label>
            <div class="row">
              <label class="grow">Endereço da câmera <input name="host" [(ngModel)]="host" required maxlength="253" inputmode="decimal" autocapitalize="none" /></label>
              <label class="port">Porta <input name="port" type="number" [(ngModel)]="port" min="1" max="65535" /></label>
            </div>
            <label>Usuário da câmera <input name="user" [(ngModel)]="username" maxlength="128" autocomplete="off" autocapitalize="none" /></label>
            <label>Senha da câmera <input name="pass" type="password" [(ngModel)]="password" maxlength="256" autocomplete="new-password" /></label>
            <label>Caminho do stream <input name="path" [(ngModel)]="path" maxlength="200" placeholder="stream1" autocapitalize="none" /></label>
            @if (error()) { <p class="form-err" role="alert">{{ error() }}</p> }
            @if (warning()) { <p class="warn" role="status">{{ warning() }}</p> }
            <button class="btn primary" type="submit" [disabled]="busy()">{{ busy() ? 'Conectando…' : 'Cadastrar' }}</button>
          </form>
        } @else {
          <p class="muted small">Câmeras conectadas ao servidor e livres:</p>
          @for (d of devices(); track d.ref) {
            <div class="dev"><span>{{ d.name }}</span><button class="btn" type="button" (click)="useLocal(d)">Usar</button></div>
          } @empty {
            <p class="muted small">{{ loaded() ? 'Nenhuma câmera livre no servidor.' : 'Procurando…' }}</p>
          }
          @if (error()) { <p class="form-err" role="alert">{{ error() }}</p> }
        }
      </div>
    </ion-content>
  `,
  styles: `
    ion-toolbar { --background: var(--panel); }
    ion-content { --background: var(--bg); }
    .body { padding: 16px; display: flex; flex-direction: column; gap: 12px; max-width: 520px; margin: 0 auto; }
    .close { margin-right: 8px; }
    .grow { flex: 1; } .port { width: 90px; }
    .warn { color: var(--warn); font-size: 12.5px; }
    .dev { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border); }
  `,
})
export class AddCameraModal implements OnInit {
  private readonly cams = inject(CamerasStore);
  private readonly modals = inject(ModalController);

  /** O Ionic entrega as componentProps atribuindo na instância: precisa ser @Input comum (não signal). */
  @Input() mode: 'rtsp' | 'local' = 'rtsp';
  readonly presets = signal<{ key: string; label: string; path: string }[]>([]);
  readonly brand = signal('generico');
  readonly devices = signal<LocalDevice[]>([]);
  readonly loaded = signal(false);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly warning = signal('');
  name = ''; host = ''; port = 554; username = ''; password = ''; path = '';

  async ngOnInit(): Promise<void> {
    this.presets.set(Object.entries(this.cams.presets()).map(([key, p]) => ({ key, ...p })));
    this.path = this.cams.presets()[this.brand()]?.path ?? '';
    if (this.mode === 'local') {
      try { this.devices.set((await this.cams.localDevices()).filter((d) => !d.mine)); }
      catch (e) { this.error.set(e instanceof Error ? e.message : 'Erro ao procurar câmeras.'); }
      this.loaded.set(true);
    }
  }

  pickBrand(key: string): void {
    this.brand.set(key);
    this.path = this.cams.presets()[key]?.path ?? '';
  }

  async saveRtsp(): Promise<void> {
    this.error.set(''); this.warning.set(''); this.busy.set(true);
    try {
      const res = await this.cams.addRtsp({ name: this.name, host: this.host.trim(), port: Number(this.port) || 554,
        username: this.username, password: this.password, path: this.path });
      this.password = '';
      if (res.warning) { this.warning.set(res.warning); setTimeout(() => void this.close(), 2500); } else await this.close();
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : 'Não foi possível cadastrar.');
    } finally {
      this.busy.set(false);
    }
  }

  async useLocal(d: LocalDevice): Promise<void> {
    this.error.set('');
    try { await this.cams.addLocal(d.ref, d.name); await this.close(); }
    catch (e) { this.error.set(e instanceof Error ? e.message : 'Não foi possível usar a câmera.'); }
  }

  close(): Promise<boolean> { return this.modals.dismiss(); }
}
