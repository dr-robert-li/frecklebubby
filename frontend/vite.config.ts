import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backend = process.env.BACKEND ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			// SPA: FastAPI serves these files and falls back to index.html.
			adapter: adapter({ pages: '../src/frecklebubby/static', fallback: 'index.html' })
		})
	],
	server: { proxy: { '/api': backend, '/mcp': backend } }
});
