import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { inject, provideAppInitializer } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { RouteReuseStrategy, provideRouter, withComponentInputBinding } from '@angular/router';
import { provideServiceWorker } from '@angular/service-worker';
import { IonicRouteStrategy, provideIonicAngular } from '@ionic/angular';

import { AppComponent } from './app/app.component';
import { routes } from './app/app.routes';
import { apiInterceptor } from './app/core/api.interceptor';
import { NativeBootstrap } from './app/core/native-bootstrap.service';
import { environment } from './environments/environment';

bootstrapApplication(AppComponent, {
  providers: [
    { provide: RouteReuseStrategy, useClass: IonicRouteStrategy },
    provideIonicAngular({ mode: 'md' }),          // mesmo visual em Android, iOS e desktop
    provideAppInitializer(() => inject(NativeBootstrap).init()),   // endereço do servidor + token (nativo)
    provideHttpClient(withInterceptors([apiInterceptor])),
    provideRouter(routes, withComponentInputBinding()),
    // service worker só da casca (ngsw-config.json); nunca cacheia /api nem /stream
    provideServiceWorker('ngsw-worker.js', { enabled: environment.pwa, registrationStrategy: 'registerWhenStable:30000' }),
  ],
});
