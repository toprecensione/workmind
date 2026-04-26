import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			// In dev, proxy /api → FastAPI on :8000
			'/api': {
				target: 'http://localhost:8000',
				changeOrigin: true,
			},
		},
	},
});
