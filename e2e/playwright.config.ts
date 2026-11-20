import { defineConfig, devices } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';

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
	`AUTH_MODE=dev DATA_DIR="$D" SLEEP_NORMS_PATH="$D/none.json" CRY_MODEL_DIR="$D/none" PORT=${PORT} exec uv run frecklebubby`
].join('\n');
// Second backend for the AI, reminder and import journeys: real model, fake Huckleberry. Web servers start
// one after the other, so this one uses the frontend that the first one built.
const llmServer = [
	'set -e',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-llm-XXXXXX)',
	`AUTH_MODE=dev HUCKLEBERRY_FAKE=1 LLM_BASE_URL=${LLM_BASE_URL} DATA_DIR="$D" SLEEP_NORMS_PATH="$D/none.json" PORT=${LLM_PORT} exec uv run --extra import frecklebubby`
].join('\n');

// Cry helper (M8): a third backend with the bundled cry models and a real cry clip as the fake
// microphone. CRY_E2E_CLIP: any audio file with a baby crying; default: a DeepInfant "hungry" clip. The WAV that
// Chromium plays is made here, in a temp folder, each run.
const CRY_PORT = Number(process.env.E2E_CRY_PORT ?? 8013);
const cryURL = `http://127.0.0.1:${CRY_PORT}`;
export const CRY_MODEL_DIR = process.env.CRY_MODEL_DIR ?? new URL('../src/frecklebubby/data/models/cry', import.meta.url).pathname;
function cryClip(): string {
	const dir = join(homedir(), 'Desktop/projects/DeepInfant/Data/v2/hungry');
	const src = process.env.CRY_E2E_CLIP ?? (existsSync(dir) ? join(dir, readdirSync(dir).filter((f) => f.endsWith('.wav')).sort()[0] ?? '') : '');
	if (!src || !existsSync(src)) return '';
	const out = join(mkdtempSync(join(tmpdir(), 'fb-cry-e2e-')), 'cry.wav');
	execFileSync('ffmpeg', ['-nostdin', '-loglevel', 'error', '-i', src, '-ac', '1', '-ar', '48000', '-c:a', 'pcm_s16le', out]);
	return out;
}
export const CRY_WAV = process.env.CRY_E2E_WAV ?? cryClip();
const cryServer = [
	'set -e',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-cry-XXXXXX)',
	`AUTH_MODE=dev CRY_MODEL_DIR="${CRY_MODEL_DIR}" DATA_DIR="$D" PORT=${CRY_PORT} exec uv run --extra cry frecklebubby`
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
		{ name: 'phone', use: phone, testIgnore: /\.(llm|m4|m5|m8|m9)\.spec\.ts$/ },
		{ name: 'llm', ...slow, testMatch: /\.llm\.spec\.ts$/, outputDir: './recordings/m3/results' },
		{ name: 'm4', ...slow, testMatch: /\.m4\.spec\.ts$/, outputDir: './recordings/m4/results' },
		{ name: 'm5', ...slow, testMatch: /\.m5\.spec\.ts$/, outputDir: './recordings/m5/results' },
		// M9 new logging: the main server (no model); the confined notification waits for the 60 s server tick.
		{ name: 'm9', use: phone, testMatch: /\.m9\.spec\.ts$/, outputDir: './recordings/m9/results', timeout: 240_000 },
		{
			name: 'm8',
			testMatch: /\.m8\.spec\.ts$/,
			outputDir: './recordings/m8/results',
			workers: 1,
			use: {
				...phone,
				baseURL: cryURL,
				permissions: ['microphone'],
				launchOptions: {
					args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
						...(CRY_WAV ? [`--use-file-for-fake-audio-capture=${CRY_WAV}`] : [])]
				}
			}
		}
	],
	webServer: [
		{ command: `bash -c '${server}'`, url: `${baseURL}/api/v1/health`, timeout: 300_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
		{ command: `bash -c '${llmServer}'`, url: `${llmURL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
		{ command: `bash -c '${cryServer}'`, url: `${cryURL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' }
	]
});
