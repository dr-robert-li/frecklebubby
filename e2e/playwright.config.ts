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

// M15: the real model with a short wait list (one request may wait), to show the waiting and busy states.
const M15_PORT = Number(process.env.E2E_M15_PORT ?? 8014);
const m15URL = `http://127.0.0.1:${M15_PORT}`;
const m15Server = [
	'set -e',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-m15-XXXXXX)',
	`AUTH_MODE=dev LLM_QUEUE_MAX=1 LLM_BASE_URL=${LLM_BASE_URL} DATA_DIR="$D" SLEEP_NORMS_PATH="$D/none.json" PORT=${M15_PORT} exec uv run frecklebubby`
].join('\n');
// M17: an invite-only server (OPERATOR_EMAILS set). The other servers keep the 0.2.2 behaviour.
const M17_PORT = Number(process.env.E2E_M17_PORT ?? 8015);
const m17URL = `http://127.0.0.1:${M17_PORT}`;
const m17Server = [
	'set -e',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-m17-XXXXXX)',
	`AUTH_MODE=dev OPERATOR_EMAILS=operator@example.com DATA_DIR="$D" SLEEP_NORMS_PATH="$D/none.json" PORT=${M17_PORT} exec uv run frecklebubby`
].join('\n');

// Voice commands: the real model and the real Whisper. VOICE_E2E_WAV: a 48 kHz WAV where a person says "Hey Bubby,
// she had a wet nappy." and then 5 s of silence (Chromium plays it again and again as the microphone). The journey
// is skipped without it. VOICE_E2E_MODEL: a folder with the Whisper model (default: download small.en).
const VOICE_PORT = Number(process.env.E2E_VOICE_PORT ?? 8016);
const voiceURL = `http://127.0.0.1:${VOICE_PORT}`;
export const VOICE_WAV = process.env.VOICE_E2E_WAV ?? '';
const voiceServer = [
	'set -e',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-voice-XXXXXX)',
	`AUTH_MODE=dev LLM_BASE_URL=${LLM_BASE_URL} WHISPER_MODEL="${process.env.VOICE_E2E_MODEL ?? 'small.en'}" DATA_DIR="$D" SLEEP_NORMS_PATH="$D/none.json" PORT=${VOICE_PORT} exec uv run --extra voice frecklebubby`
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
		{ name: 'phone', use: phone, testIgnore: /\.(llm|m4|m5|m8|m9|m11|m13|m14|m15|m17|m18)\.spec\.ts$/ },
		{ name: 'llm', ...slow, testMatch: /\.llm\.spec\.ts$/, outputDir: './recordings/m3/results' },
		{ name: 'm4', ...slow, testMatch: /\.m4\.spec\.ts$/, outputDir: './recordings/m4/results' },
		{ name: 'm5', ...slow, testMatch: /\.m5\.spec\.ts$/, outputDir: './recordings/m5/results' },
		// M11 support report: the real model on the second server.
		{ name: 'm11', ...slow, testMatch: /\.m11\.spec\.ts$/, outputDir: './recordings/m11/results' },
		// M13 development guidance and M14 logging from the assistant: the real model on the second server.
		{ name: 'm13', ...slow, testMatch: /\.m13\.spec\.ts$/, outputDir: './recordings/m13/results' },
		{ name: 'm14', ...slow, testMatch: /\.m14\.spec\.ts$/, outputDir: './recordings/m14/results' },
		// M15 delete family and the assistant's waiting and busy states (real model, wait list of 1); M17 invite only.
		{ name: 'm15', ...slow, use: { ...phone, baseURL: m15URL }, testMatch: /\.m15\.spec\.ts$/, outputDir: './recordings/m15/results' },
		{ name: 'm17', use: { ...phone, baseURL: m17URL }, testMatch: /\.m17\.spec\.ts$/, outputDir: './recordings/m17/results', workers: 1 },
		// M9 new logging: the main server (no model); the confined notification waits for the 60 s server tick.
		{ name: 'm9', use: phone, testMatch: /\.m9\.spec\.ts$/, outputDir: './recordings/m9/results', timeout: 240_000 },
		{
			name: 'm18',
			...slow,
			testMatch: /\.m18\.spec\.ts$/,
			outputDir: './recordings/m18/results',
			use: {
				...phone,
				baseURL: voiceURL,
				permissions: ['microphone'],
				launchOptions: {
					args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
						...(VOICE_WAV ? [`--use-file-for-fake-audio-capture=${VOICE_WAV}`] : [])]
				}
			}
		},
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
		{ command: `bash -c '${m15Server}'`, url: `${m15URL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
		{ command: `bash -c '${m17Server}'`, url: `${m17URL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
		{ command: `bash -c '${voiceServer}'`, url: `${voiceURL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
		{ command: `bash -c '${cryServer}'`, url: `${cryURL}/api/v1/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' }
	]
});
