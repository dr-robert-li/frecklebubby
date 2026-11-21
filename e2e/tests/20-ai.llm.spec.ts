// AI journeys against the real backend and the real model server (no route mocks). Project `llm`.
import type { Locator, Page } from '@playwright/test';
import { expect, local, openTile, seedSleepWeek, setAge, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm3');
const MODEL_URL = process.env.LLM_BASE_URL ?? 'http://127.0.0.1:8082/v1';
const nl = (page: Page) => page.getByRole('textbox', { name: 'Tell me what happened' });
const timeline = (page: Page) => page.getByRole('list', { name: 'Timeline' });
/** "HH:MM" of `minutes` ago, and the minute before (the model call takes a few seconds). */
const near = (minutes: number) => [0, 1].map((d) => local(Date.now() - (minutes + d) * 60_000).slice(11)).join('|');

async function readWords(page: Page, text: string) {
	await nl(page).fill(text);
	await page.getByRole('button', { name: 'Read my words' }).click();
	await expect(page.getByText('Reading…')).toBeHidden({ timeout: 60_000 });
}

/** Ask the assistant and wait for the whole answer. Returns the answer bubble. */
async function ask(page: Page, question: string, midShot?: string): Promise<Locator> {
	await page.getByLabel('Your question').fill(question);
	await page.getByRole('button', { name: 'Send' }).click();
	const answer = page.locator('.msgs li.assistant').last();
	if (midShot) {
		await expect(answer).not.toHaveText('…', { timeout: 60_000 });
		await snap(page, midShot);
	}
	await expect(answer).toContainText('General information, not medical advice.', { timeout: 120_000 });
	return answer;
}

/** Each [n] mark in the answer text has a chip with the same number; no unlinked [n] is left in the text. */
async function checkCitations(answer: Locator) {
	const marks = (await answer.getByRole('button', { name: /^Source \d+$/ }).allInnerTexts()).map(Number);
	const chips = (await answer.locator('.cite').allInnerTexts()).map((t) => Number(/^\[(\d+)\]/.exec(t)![1]));
	for (const n of marks) expect(chips, `chip for mark ${n}`).toContain(n);
	expect((await answer.locator('p').allInnerTexts()).join('\n')).not.toMatch(/\[\d+\]/);
	return { marks, chips };
}

test('a: the parent logs by plain words, starts and stops a sleep, and gets a kind message for nonsense', async ({ page, family }) => {
	await page.goto('/');
	await readWords(page, 'she had 120ml of formula 20 minutes ago and a wet nappy just now');
	const bottleAt = near(20), nappyAt = near(0);
	await expect(page.getByText('I found 2 items. Check and confirm.')).toBeVisible();
	await expect(page.getByText(new RegExp(`^Bottle – 120 ml formula – (${bottleAt})$`))).toBeVisible();
	await expect(page.getByText(new RegExp(`^Nappy – wee – (${nappyAt})$`))).toBeVisible();
	await snap(page, 'a1-nl-preview');
	await page.getByRole('button', { name: 'Save these 2' }).click();
	await expect(page.getByText('Saved 2 items')).toBeVisible();
	await expect(timeline(page).getByRole('button', { name: new RegExp(`^Edit Bottle at (${bottleAt})$`) })).toContainText('120 ml');
	await expect(timeline(page).getByRole('button', { name: new RegExp(`^Edit Nappy at (${nappyAt})$`) })).toBeVisible();
	await snap(page, 'a2-nl-saved', true);

	await readWords(page, 'she just fell asleep');
	await expect(page.getByText(/^Sleep timer – start/)).toBeVisible();
	await page.getByRole('button', { name: 'Save this' }).click();
	await expect(page.getByRole('region', { name: 'Sleep timer' })).toBeVisible();
	await snap(page, 'a3-sleep-timer');

	await readWords(page, "she's awake");
	await expect(page.getByText(/^Sleep timer – stop and save/)).toBeVisible();
	await page.getByRole('button', { name: 'Save this' }).click();
	await expect(page.getByRole('region', { name: 'Sleep timer' })).toBeHidden();
	await expect(timeline(page).getByRole('button', { name: /^Edit Sleep/ })).toBeVisible();
	await expect(timeline(page).getByRole('listitem')).toHaveCount(3);

	await readWords(page, 'asdf qwerty zxcv');
	await expect(page.getByText(/I did not find anything to log/)).toBeVisible();
	await expect(page.getByRole('button', { name: /^Save/ })).toHaveCount(0);
	await snap(page, 'a4-nl-nothing');
	await page.getByRole('button', { name: 'Cancel' }).click();
	await expect(timeline(page).getByRole('listitem')).toHaveCount(3);
});

test('b1: a 6-week-old with a fever: urgent text first, streamed answer, sources', async ({ page, api, family }) => {
	await setAge(api, family.childId, 42);
	await api.post(`children/${family.childId}/entries`, { data: { type: 'temperature', started_at: local(), data: { celsius: 38.3 } } });
	await page.goto('/assistant');
	const answer = await ask(page, 'She feels hot, what should I do?', 'b1-chat-streaming');
	await expect(answer.locator('p').first()).toHaveText(/^Urgent: /);
	await expect(answer.locator('.cite').first()).toBeVisible();
	await checkCitations(answer);
	await expect(page.locator('.disclaimer')).toHaveText('General information, not medical advice.');
	await snap(page, 'b1-chat-answer');

	await answer.locator('.cite').first().click();
	const src = page.getByRole('dialog');
	await expect(src.getByRole('heading', { name: /^\[\d+\] / })).toBeVisible();
	await expect(src.getByText(/NHS|healthdirect|Pregnancy, Birth and Baby|CDC/).first()).toBeVisible();
	await expect(src.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /^https:\/\//);
	await snap(page, 'b1-source');
});

test('b2: an 8-month-old: safe sleep is cited, car seats are not covered, history stays, clear works', async ({ page, api, family }) => {
	await setAge(api, family.childId, 245);
	await page.goto('/assistant');
	const sleep = await ask(page, 'How should I put her down to sleep safely?');
	const { chips } = await checkCitations(sleep);
	expect(chips.length).toBeGreaterThan(0);
	await snap(page, 'b2-safe-sleep');

	const car = await ask(page, 'What car seat should I buy?');
	// the new question scrolls up into view, the answer below it
	await expect(page.locator('.msgs li.user').last()).toBeInViewport();
	await expect(car).toBeInViewport();
	await expect(car).toContainText(/do not cover|don't cover|not covered/i);
	// 0.4.3: a "not covered" answer lists trusted pages on the topic as links.
	await expect(car).toContainText('These trusted pages are about this topic');
	expect(await car.locator('.cite').count()).toBeGreaterThan(0);
	await snap(page, 'b2-car-seat');

	await page.reload();
	await expect(page.locator('.msgs li')).toHaveCount(4);
	await expect(page.locator('.msgs li.user').first()).toHaveText('How should I put her down to sleep safely?');
	await snap(page, 'b2-after-reload');
	await page.getByRole('button', { name: 'Clear chat' }).click();
	await expect(page.locator('.msgs li')).toHaveCount(0);
	await page.reload();
	await expect(page.getByText(/Ask about sleep, feeding or development/)).toBeVisible();
});

test('c: insights show the urgent fever card first, milestones with CDC and the sleep total', async ({ page, api, family }) => {
	await setAge(api, family.childId, 42);
	await seedSleepWeek(api, family.childId);
	await api.post(`children/${family.childId}/entries`, { data: { type: 'temperature', started_at: local(), data: { celsius: 38.3 } } });
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Insights' }).click();
	const cards = page.getByRole('article');
	await expect(cards.first()).toHaveClass(/urgent/);
	await expect(cards.first()).toContainText(/temperature/i);
	const ms = cards.filter({ hasText: /milestones by 2 months/i });
	await expect(ms).toBeVisible();
	await expect(ms.locator('.cite').first()).toContainText('CDC');
	await expect(cards.filter({ hasText: /sleep/i }).filter({ hasNotText: /milestone/i }).first()).toBeVisible();
	await snap(page, 'c1-insights');
	await snap(page, 'c2-insights-bottom', true);
});

test('d: the sleep plan for an 8-month-old shows a waiting state, then a cited plan', async ({ page, api, family }) => {
	await setAge(api, family.childId, 245);
	await seedSleepWeek(api, family.childId);
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const calc = page.getByRole('region', { name: 'Day and night plan' });
	await expect(calc.locator('.schedule li.night')).toContainText('to 05:40'); // the child's own night, with no model
	expect(await calc.locator('.schedule li.nap').count()).toBeGreaterThanOrEqual(1);
	await page.getByRole('button', { name: 'Write a sleep plan' }).click();
	const waiting = page.getByRole('button', { name: /Writing the sleep plan/ });
	await expect(waiting).toBeDisabled();
	await page.waitForTimeout(5000);
	await snap(page, 'd1-plan-waiting');
	await expect(waiting).toBeHidden({ timeout: 240_000 });
	const plan = page.getByRole('region', { name: 'Sleep plan' });
	await expect(plan.getByRole('heading', { name: 'Sleep plan in words' })).toBeVisible();
	await expect(plan.getByRole('listitem').first()).toBeVisible();
	await expect(plan.locator('.cite').first()).toBeVisible();
	// every advice mark has a chip
	const chips = (await plan.locator('.cite').allInnerTexts()).map((t) => Number(/^\[(\d+)\]/.exec(t)![1]));
	for (const n of (await plan.getByRole('button', { name: /^Source \d+$/ }).allInnerTexts()).map(Number)) expect(chips).toContain(n);
	await snap(page, 'd2-plan');
	await snap(page, 'd3-plan-bottom', true);
});

test('e: the parent uploads a text file and a PDF, the assistant cites them, then the upload is deleted', async ({ page, browser, family }) => {
	// a small PDF made by the browser, with a made-up fact
	const maker = await browser.newPage();
	await maker.setContent('<title>Grandma notes</title><h1>Grandma notes</h1><p>Grandma Wilhelmina sings the lullaby called Moonlit Kookaburra at bedtime.</p>');
	const pdf = await maker.pdf();
	await maker.close();
	const txt = Buffer.from('# Nurse visit\n\nNurse Quorinda Platt said the Zebrafinch sleeping bag for Mia must be TOG 2.5 in winter.\n');

	await page.goto('/settings/knowledge');
	const file = page.getByLabel(/Choose a file/);
	await file.setInputFiles({ name: 'nurse-visit.md', mimeType: 'text/markdown', buffer: txt });
	await expect(page.getByRole('listitem').filter({ hasText: 'nurse-visit' })).toBeVisible();
	await file.setInputFiles({ name: 'grandma.pdf', mimeType: 'application/pdf', buffer: pdf });
	await expect(page.getByRole('listitem').filter({ hasText: 'Grandma notes' })).toBeVisible();
	await snap(page, 'e1-uploads');

	await page.goto('/assistant');
	const a1 = await ask(page, 'What lullaby does Grandma Wilhelmina sing?');
	await expect(a1).toContainText(/Moonlit Kookaburra/i);
	await expect(a1.locator('.cite').filter({ hasText: 'Grandma notes' })).toBeVisible();
	const a2 = await ask(page, 'What TOG must the Zebrafinch sleeping bag be?');
	await expect(a2).toContainText('2.5');
	await expect(a2.locator('.cite').filter({ hasText: 'nurse-visit' })).toBeVisible();
	await checkCitations(a2);
	await snap(page, 'e2-upload-answer');
	await a2.locator('.cite').filter({ hasText: 'nurse-visit' }).click();
	await expect(page.getByRole('dialog').getByText('Your family upload')).toBeVisible();
	await snap(page, 'e3-upload-source');
	await page.getByRole('button', { name: 'Close' }).click();

	await page.goto('/settings/knowledge');
	await page.getByRole('button', { name: 'Delete nurse-visit' }).click();
	await expect(page.getByRole('listitem').filter({ hasText: 'nurse-visit' })).toHaveCount(0);
	await page.getByRole('button', { name: 'Delete Grandma notes' }).click();
	await expect(page.getByRole('listitem').filter({ hasText: 'Grandma notes' })).toHaveCount(0);
});

test('f: model settings: test passes, a wrong URL fails plainly, the assistant says so, trackers still work', async ({ page, family }) => {
	await page.goto('/settings/ai');
	const url = page.getByLabel('Server URL');
	await expect(url).toHaveValue(MODEL_URL);
	await page.getByRole('button', { name: 'Test connection' }).click();
	await expect(page.getByText(/^Connected\./)).toBeVisible({ timeout: 60_000 });
	await snap(page, 'f1-test-ok');

	await url.fill('http://127.0.0.1:9/v1');
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByText('AI settings saved')).toBeVisible();
	await page.getByRole('button', { name: 'Test connection' }).click();
	await expect(page.getByText(/^Not connected\./)).toBeVisible({ timeout: 60_000 });
	await snap(page, 'f2-test-fail');

	await page.goto('/assistant');
	await page.getByLabel('Your question').fill('Is she eating enough?');
	await page.getByRole('button', { name: 'Send' }).click();
	await expect(page.getByRole('alert')).toHaveText('The assistant is not available now.');
	await snap(page, 'f3-assistant-down');

	await page.goto('/');
	await openTile(page, 'Bottle');
	await page.getByRole('dialog').getByLabel('Amount (ml)').fill('90');
	await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
	await expect(timeline(page).getByRole('button', { name: /Edit Bottle/ })).toContainText('90 ml');
	await readWords(page, 'bottle 100 ml');
	await expect(page.getByRole('alert')).toHaveText('The assistant is not available now.');

	await page.goto('/settings/ai');
	await url.fill(MODEL_URL);
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByText('AI settings saved')).toBeVisible();
	await page.getByRole('button', { name: 'Test connection' }).click();
	await expect(page.getByText(/^Connected\./)).toBeVisible({ timeout: 60_000 });
});
