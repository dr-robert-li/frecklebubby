// M8 cry helper when the parent blocks the microphone.
import { expect, shot, test } from './fixtures';

test.use({ permissions: [], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream=deny'] } });

test('microphone blocked: a plain message, and the no-audio path still works', async ({ page, family }) => {
	await page.goto('/');
	await page.getByRole('button', { name: /^Crying\?/ }).click();
	const s = page.getByRole('dialog');
	await s.getByRole('button', { name: /^Listen/ }).click();
	await expect(s.getByRole('alert')).toContainText('Microphone access is blocked');
	await shot(page, '11-mic-blocked', false, 'm8');
	await s.getByRole('button', { name: /Just tell me what to check/ }).click();
	await expect(s.getByRole('heading', { name: /Most likely/ })).toBeVisible();
	void family;
});
