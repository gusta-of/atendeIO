// Build desktop (janela Electron, servido pelo motor local em /app/): sem service worker, o próprio app instalado já é "offline".
export const environment = {
  production: true,
  pwa: false,
  desktop: true,   // dono local único: não há login nem "Sair"
};
