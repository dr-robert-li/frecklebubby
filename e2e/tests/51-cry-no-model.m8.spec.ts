// M8 cry helper on a server without the model files: the sound block says so in one line; the rest works.
import { expect, shot, test } from './fixtures';

const PORT = Number(process.env.E2E_PORT ?? 8011); // the main e2e server has no cry models
test.use({ baseURL: `http://127.0.0.1:${PORT}`, launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] } });

test('listen without the model: one plain line, and the logs still help', async ({ page, family }) => {
	await page.goto('/');
	await page.getByRole('button', { name: /^Crying\?/ }).click();
	const s = page.getByRole('dialog');
	await s.getByRole('button', { name: /^Listen/ }).click();
	const sound = s.getByRole('region', { name: /From the sound/ });
	await expect(sound).toContainText('Sound analysis is not installed on this server.', { timeout: 30_000 });
	await expect(s.getByRole('heading', { name: /Most likely/ })).toBeVisible();
	await expect(s.getByRole('heading', { name: 'Things to try' })).toBeVisible();
	await shot(page, '10-no-model', false, 'm8');
	void family;
});
