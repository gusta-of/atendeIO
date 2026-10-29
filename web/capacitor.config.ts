import type { CapacitorConfig } from '@capacitor/cli';

/**
 * App nativo (Android/iOS). O código vem do build `native` (`npm run build:native` → www-native), empacotado no
 * aparelho; ele fala com o SEU servidor atendeIO (endereço pedido na primeira abertura).
 *
 * Origem das requisições do app (precisa estar em ATENDEIO_CORS_ORIGINS no servidor):
 *   iOS     → capacitor://localhost
 *   Android → https://localhost   (androidScheme abaixo)
 */
const config: CapacitorConfig = {
  appId: 'com.atendeio.app',
  appName: 'atendeIO',
  webDir: 'www-native',
  backgroundColor: '#121826',
  server: {
    androidScheme: 'https',
    // Só em DESENVOLVIMENTO (servidor http na rede local). Em produção use HTTPS e deixe false.
    cleartext: false,
  },
  ios: { contentInset: 'always' },
  plugins: {
    StatusBar: { style: 'DARK', backgroundColor: '#121826' },
    Keyboard: { resize: 'body' },
  },
};

export default config;
