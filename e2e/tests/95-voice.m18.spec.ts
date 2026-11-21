// M18: voice commands. Project `m18`: the real model and the real Whisper; Chromium plays a WAV as the microphone
// ("Hey Bubby, she had a wet nappy.", then silence, again and again).
import type { Page } from '@playwright/test';
import { VOICE_WAV } from '../playwright.config';
import { expect, shot, test } from './fixtures';

const snap = (page: Page, name: string) => shot(page, name, false, 'm18');
const card = (page: Page) => page.getByRole('complementary', { name: 'Voice commands' });

test.skip(!VOICE_WAV, 'Set VOICE_E2E_WAV to a WAV with the words "Hey Bubby, she had a wet nappy."');

test('a: hands free hears the keyword, logs the nappy and shows it', async ({ page, family }) => {
	await page.goto('/');
	await page.getByRole('button', { name: 'Hands free: listen for "Hey Bubby"' }).click();
	await expect(card(page)).toContainText('Hands free is on');
	await snap(page, 'a1-hands-free-on');
	await expect(card(page).getByText(/^You said: she had a wet nappy/i)).toBeVisible({ timeout: 120_000 });
	await expect(card(page).getByText(/Nappy – wee/)).toBeVisible({ timeout: 120_000 });
	await card(page).getByRole('button', { name: 'Turn off' }).click();
	await snap(page, 'a2-logged');
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /^Edit Nappy at / }).first()).toBeVisible();
	// Undo from the voice card.
	await card(page).getByRole('button', { name: /^Undo Nappy/ }).first().click();
	await expect(card(page).getByText('Undone').first()).toBeVisible();
});

test('b: the talk button in the Assistant puts the command in the chat', async ({ page, family }) => {
	await page.goto('/assistant');
	await page.getByRole('button', { name: 'Talk: start recording' }).click();
	await expect(card(page)).toContainText('Recording');
	await page.waitForTimeout(9000); // one full turn of the WAV
	await page.getByRole('button', { name: 'Stop recording and send' }).click();
	await expect(card(page).getByRole('progressbar')).toBeVisible(); // the speech is received and the app works on it
	await expect(card(page)).toContainText(/Changing speech to words|Working/);
	const turn = page.locator('.msgs li.assistant').last();
	await expect(turn.getByRole('group', { name: 'Logged' }).getByText(/Nappy – wee/).first()).toBeVisible({ timeout: 120_000 });
	await expect(page.locator('.msgs li.user').last()).toContainText(/wet nappy/i);
	await snap(page, 'b1-talk-in-chat');
});

test('c: the hold-to-talk button on the side, and read aloud, are in Settings', async ({ page, family }) => {
	await page.goto('/settings/voice');
	await page.getByLabel('Show a large hold-to-talk button').check();
	await page.getByRole('button', { name: 'Left' }).click();
	const hold = page.getByRole('button', { name: 'Hold to talk' });
	await expect(hold).toBeVisible();
	expect((await hold.boundingBox())!.x).toBe(0);
	await page.getByRole('group', { name: 'Read the answer aloud' }).getByRole('button', { name: 'All voice' }).click();
	await snap(page, 'c1-settings');
	await page.goto('/');
	await expect(page.getByRole('button', { name: 'Hold to talk' })).toBeVisible(); // kept for this device, on all pages
	const box = (await page.getByRole('button', { name: 'Hold to talk' }).boundingBox())!;
	await page.mouse.move(box.x + 20, box.y + 20);
	await page.mouse.down();
	await expect(card(page)).toContainText('Recording');
	await page.waitForTimeout(9000);
	await page.mouse.up();
	await expect(card(page).getByText(/Nappy – wee/).first()).toBeVisible({ timeout: 120_000 });
	await snap(page, 'c2-hold-to-talk');
});
