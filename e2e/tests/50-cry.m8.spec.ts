// M8 cry helper: "Just tell me what to check" (no audio) and "Listen" with a real cry clip as the fake microphone.
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { CRY_MODEL_DIR, CRY_WAV } from '../playwright.config';
import { expect, local, shot, test, type Page } from './fixtures';

const shotM8 = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm8');
const ago = (min: number) => local(Date.now() - min * 60_000);

test('no microphone: the logs rank what to check, then the parent saves the crying time', async ({ page, api, family }) => {
	// Feeds every 2 h 30 min; the last one 4 h ago. A nap that ended 3 h 10 min ago.
	for (const min of [240, 390, 540, 690, 840])
		expect((await api.post(`children/${family.childId}/entries`, { data: { type: 'bottle', started_at: ago(min), data: { amount_ml: 150 } } })).ok()).toBeTruthy();
	expect((await api.post(`children/${family.childId}/entries`, { data: { type: 'sleep', started_at: ago(250), ended_at: ago(190), data: {} } })).ok()).toBeTruthy();
	expect((await api.post(`children/${family.childId}/entries`, { data: { type: 'nappy', started_at: ago(60), data: { mode: 'pee' } } })).ok()).toBeTruthy();

	await page.goto('/');
	await shotM8(page, '01-home-cry-tile');
	await page.getByRole('button', { name: /^Crying\?/ }).click();
	const s = page.getByRole('dialog');
	await expect(s.getByRole('heading', { name: 'Why is Mia crying?' })).toBeVisible();
	await shotM8(page, '02-cry-start');
	await s.getByRole('button', { name: /Just tell me what to check/ }).click();

	const first = s.getByRole('listitem').filter({ hasText: /^1\./ });
	await expect(first).toContainText('Hungry');
	await expect(first).toContainText(/Last feed 4 h [01] min ago/); // the minute can turn while the test runs
	await expect(first).toContainText("usual time between feeds is 2 h 30 min");
	await expect(s.getByRole('heading', { name: /From the sound/ })).toHaveCount(0); // no audio: no sound block
	await expect(s.getByText('General information, not medical advice.')).toBeVisible();
	await shotM8(page, '03-check-result');
	await s.getByRole('heading', { name: 'Get medical help' }).scrollIntoViewIfNeeded();
	await shotM8(page, '04-check-help');

	await s.getByLabel('Crying for about').selectOption('15');
	await s.getByLabel('What helped (optional)').fill('feed');
	await s.getByRole('button', { name: 'Save to timeline' }).click();
	await expect(s).toBeHidden();
	const item = page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Crying/ });
	await expect(item).toContainText('Helped: feed');
	await expect(item).toContainText('Most likely: hungry'); // the first reason of the list in the sheet
	await expect(item).toContainText('15 min');
	await shotM8(page, '05-timeline', true);

	const saved = (await (await api.get(`children/${family.childId}/entries?type=cry`)).json())[0];
	expect(saved.data.likely_needs[0]).toBe('hunger');
	expect(saved.data.sound_reason).toBeUndefined();
});

test('listen: a real cry clip goes through the experimental sound model', async ({ page, family }) => {
	test.skip(!CRY_WAV, 'No cry clip: set CRY_E2E_CLIP to an audio file with a baby crying.');
	test.skip(!existsSync(join(CRY_MODEL_DIR, 'model_card.json')), `No cry model in ${CRY_MODEL_DIR}: set CRY_MODEL_DIR.`);
	await page.goto('/');
	await page.getByRole('button', { name: /^Crying\?/ }).click();
	const s = page.getByRole('dialog');
	await s.getByRole('button', { name: /^Listen/ }).click();
	await expect(s.getByText('Listening…')).toBeVisible();
	await shotM8(page, '06-listening');
	const sound = s.getByRole('region', { name: /From the sound/ });
	await expect(sound).toBeVisible({ timeout: 30_000 });
	await expect(sound).toContainText('Experimental');
	await expect(sound).toContainText('A guess, not a diagnosis.');
	await expect(sound).toContainText('In tests on babies the model had not heard');
	await expect(sound.getByRole('listitem').first()).toContainText('%');
	await shotM8(page, '07-listen-result');
	await sound.scrollIntoViewIfNeeded();
	await shotM8(page, '08-listen-sound-block');
	await s.getByRole('button', { name: 'Save to timeline' }).click();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Crying/ })).toContainText(/Most likely: .+ · Sound alone: .+ \(experimental\)/);
	await shotM8(page, '09-listen-saved', true);
	void family;
});
