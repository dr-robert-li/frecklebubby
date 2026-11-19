import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 8011);
const LLM_PORT = Number(process.env.E2E_LLM_PORT ?? 8012);
export const baseURL = `http://127.0.0.1:${PORT}`;
const llmURL = `http://127.0.0.1:${LLM_PORT}`;
// The real model server for the AI journeys (llama.cpp with the bundled model).
const LLM_BASE_URL = process.env.LLM_BASE_URL ?? 'http://127.0.0.1:8082/v1';

// The real backend in dev sign-in mode, with a fresh empty data folder, serving the built frontend.
const server = [
	'set -e',
	'cd ../frontend && npm run build',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-XXXXXX)',
	`AUTH_MODE=dev DATA_DIR="$D" PORT=${PORT} exec uv run frecklebubby`
].join('\n');
// Second backend for the AI, reminder and import journeys: real model, fake Huckleberry. Web servers start
// one after the other, so this one uses the frontend that the first one built.
const llmServer = [
	'set -e',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-llm-XXXXXX)',
	`AUTH_MODE=dev HUCKLEBERRY_FAKE=1 LLM_BASE_URL=${LLM_BASE_URL} DATA_DIR="$D" PORT=${LLM_PORT} exec uv run --extra import frecklebubby`
].join('\n');

const phone = { ...devices['Pixel 7'], browserName: 'chromium' as const };
// Real-model journeys: one at a time (one CPU model), long timeouts.
const slow = { testDir: './tests', timeout: 600_000, workers: 1, use: { ...phone, baseURL: llmURL } };

export default defineConfig({
	testDir: './tests',
	outputDir: './recordings/m2/results',
	timeout: 90_000,
	expect: { timeout: 15_000 },
	workers: 2,
	reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
	use: {
		...phone,
		baseURL,
		locale: 'en-AU',
		timezoneId: 'Australia/Brisbane',
		video: 'on',
		trace: 'on',
		screenshot: 'on'
	},
	projects: [
		{ name: 'phone', use: phone, testIgnore: /\.(llm|m4|m5)\.spec\.ts$/ },
		{ name: 'llm', ...slow, testMatch: /\.llm\.spec\.ts$/, outputDir: './recordings/m3/results' },
		{ name: 'm4', ...slow, testMatch: /\.m4\.spec\.ts$/, outputDir: './recordings/m4/results' },
		{ name: 'm5', ...slow, testMatch: /\.m5\.spec\.ts$/, outputDir: './recordings/m5/results' }
	],
	webServer: [
		{ command: `bash -c '${server}'`, url: `${baseURL}/api/v1/health`, timeout: 300_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
		{ command: `bash -c '${llmServer}'`, url: `${llmURL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' }
	]
});
