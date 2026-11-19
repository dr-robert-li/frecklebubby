import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 8011);
export const baseURL = `http://127.0.0.1:${PORT}`;

// The real backend in dev sign-in mode, with a fresh empty data folder, serving the built frontend.
const server = [
	'set -e',
	'cd ../frontend && npm run build',
	'cd .. && D=$(mktemp -d -t frecklebubby-e2e-XXXXXX)',
	`AUTH_MODE=dev DATA_DIR="$D" PORT=${PORT} exec uv run frecklebubby`
].join('\n');

export default defineConfig({
	testDir: './tests',
	outputDir: './recordings/m2/results',
	timeout: 90_000,
	expect: { timeout: 15_000 },
	workers: 2,
	reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
	use: {
		...devices['Pixel 7'],
		baseURL,
		locale: 'en-AU',
		timezoneId: 'Australia/Brisbane',
		video: 'on',
		trace: 'on',
		screenshot: 'on'
	},
	projects: [{ name: 'phone', use: { browserName: 'chromium' } }],
	webServer: {
		command: `bash -c '${server}'`,
		url: `${baseURL}/api/v1/health`,
		timeout: 300_000,
		reuseExistingServer: false,
		stdout: 'ignore',
		stderr: 'pipe'
	}
});
