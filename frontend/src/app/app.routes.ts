import { Routes } from '@angular/router';

import { authGuard } from './core/auth.guard';

export const routes: Routes = [
  { path: 'servidor', loadComponent: () => import('./features/server/server.page').then((m) => m.ServerPage) },
  { path: 'login', loadComponent: () => import('./features/login/login.page').then((m) => m.LoginPage) },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./features/shell/shell.page').then((m) => m.ShellPage),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'cameras' },
      { path: 'cameras', loadComponent: () => import('./features/cameras/cameras.page').then((m) => m.CamerasPage) },
      { path: 'analise', loadComponent: () => import('./features/analytics/analytics.page').then((m) => m.AnalyticsPage) },
    ],
  },
  { path: '**', redirectTo: '' },
];
