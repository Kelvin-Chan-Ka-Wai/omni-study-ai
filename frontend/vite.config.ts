import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { output: { manualChunks: { study: ['katex', 'rehype-katex', 'react-markdown', 'remark-math'] } } } },
  server: {
    port: 5173,
    strictPort: true,
  },
});
