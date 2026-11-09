import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
    // upstream page tests assume one stored-close load; the live-quote pass has its own test
    env: { VITE_PORTFOLIO_LIVE_QUOTES: 'false' },
    exclude: [...configDefaults.exclude, 'e2e/**', 'playwright.config.ts'],
  },
});
