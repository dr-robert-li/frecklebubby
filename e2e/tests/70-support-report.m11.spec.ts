// M11 support report on the Reports page. Project `m11`: the real model on the second server.
import type { APIRequestContext, Locator, Page } from '@playwright/test';
import { expect, local, setAge, shot, test } from './fixtures';

const snap = (page: Page, name: string) => shot(page, name, false, 'm11');
/** Scroll an element to the top of the screen (below the child bar), then take the screenshot. */
const snapAt = async (page: Page, el: Locator, name: string) => {
	await el.evaluate((e) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 16));
	await snap(page, name);
};
const DAY = 86400_000;
const day = (n: number) => local(Date.now() - n * DAY).slice(0, 10);
const FOOTER = 'General information, not medical advice.';
const NOTICE = 'The AI model is not available. These are the standard tips.';

/** Past days only (never today), so no check depends on the clock. */
async function seedWeek(api: APIRequestContext, childId: number) {
	const rows: unknown[] = [];
	for (let n = 1; n <= 7; n++) {
		rows.push({ type: 'sleep', started_at: `${day(n)}T09:00`, ended_at: `${day(n)}T17:00`, data: {} });
		rows.push({ type: 'bottle', started_at: `${day(n)}T11:00`, data: { amount_ml: 120, milk_type: 'Formula' } });
	}
	for (let n = 1; n <= 3; n++) {
		for (const h of ['08', '12', '16']) rows.push({ type: 'nappy', started_at: `${day(n)}T${h}:00`, data: { mode: 'pee' } });
		rows.push({ type: 'play', started_at: `${day(n)}T10:00`, ended_at: `${day(n)}T10:20`, data: { tummy_seconds: 300 } });
	}
	rows.push({ type: 'confined', started_at: `${day(2)}T13:00`, ended_at: `${day(2)}T14:30`, data: { device: 'car_seat' } });
	for (const data of rows) expect((await api.post(`children/${childId}/entries`, { data })).ok(), JSON.stringify(data)).toBeTruthy();
}

/** Each mark in an area has a chip with the same number in that area. */
async function checkMarks(area: Locator) {
	const marks = (await area.getByRole('button', { name: /^Source \d+$/ }).allInnerTexts()).map(Number);
	const chips = (await area.locator('.cite').allInnerTexts()).map((t) => Number(/^\[(\d+)\]/.exec(t)![1]));
	for (const n of marks) expect(chips, `chip for mark ${n}`).toContain(n);
	return marks;
}

async function makeReport(page: Page) {
	const card = page.getByRole('region', { name: 'Support report' });
	await expect(card.getByRole('heading', { name: 'How can I support Mia?', exact: true })).toBeVisible();
	await card.getByRole('button', { name: 'Make the report', exact: true }).click();
	const waiting = card.getByRole('button', { name: /^Making the report… this can take a minute or two$/ });
	await expect(waiting).toBeDisabled();
	return { card, waiting };
}

test('a: a 4-month-old: waiting state, cited suggestions, a source, and the saved report after reload', async ({ page, api, family }) => {
	await setAge(api, family.childId, 130);
	await seedWeek(api, family.childId);
	await page.goto('/reports');
	const { card, waiting } = await makeReport(page);
	await snap(page, 'a1-waiting');
	const t0 = Date.now();
	await expect(waiting).toBeHidden({ timeout: 300_000 });
	console.log(`support report with the real model: ${Math.round((Date.now() - t0) / 1000)} s`);

	await expect(card.getByText(/^Made \d+ \w+ · the last 7 days and today$/)).toBeVisible();
	await expect(card.getByText(NOTICE, { exact: true })).toHaveCount(0);
	const area = (name: string) => card.getByRole('article', { name, exact: true });
	for (const name of ['Sleep', 'Nappies', 'Play and tummy time', 'Time in a seat or pram'])
		await expect(area(name).locator('.status')).toHaveText('Ideas to try');
	await expect(area('Feeds').locator('.status')).toHaveText('Logged');
	await expect(area('Milestones by 4 months').locator('.status')).toHaveText('Logged');
	await expect(area('Sleep').getByText('Average a day (7 logged days)', { exact: true })).toBeVisible();
	await expect(area('Sleep').getByText('8 h 00 min', { exact: true })).toBeVisible();
	await expect(area('Play and tummy time').getByText(/^WHO: at least 30 minutes of tummy time a day/)).toBeVisible();
	await expect(card.getByText(/^Nothing logged in these 8 days: .*Growth/)).toBeVisible();

	// The model wrote the ideas for at least one area; every mark has its chip.
	await expect(card.getByRole('heading', { name: 'Ideas to try', exact: true }).first()).toBeVisible();
	let marked = 0;
	for (const name of ['Sleep', 'Nappies', 'Play and tummy time', 'Time in a seat or pram']) {
		await expect(area(name).locator('.tips li').first()).toBeVisible();
		marked += (await checkMarks(area(name))).length;
	}
	expect(marked).toBeGreaterThan(0);
	await expect(card.locator('.disclaimer')).toHaveText(FOOTER);
	await snapAt(page, area('Sleep'), 'a2-report-sleep');
	await snapAt(page, area('Play and tummy time'), 'a3-report-play');
	await snapAt(page, area('Time in a seat or pram'), 'a4-report-confined');
	await snapAt(page, card.locator('.disclaimer'), 'a5-report-end');

	await area('Play and tummy time').locator('.cite').first().click();
	const src = page.getByRole('dialog');
	await expect(src.getByRole('heading', { name: /^\[1\] / })).toBeVisible();
	await expect(src.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /^https:\/\//);
	await snap(page, 'a6-source');
	await page.getByRole('button', { name: 'Close' }).click();

	const tips = await area('Sleep').locator('.tips li').allInnerTexts();
	await page.reload();
	await expect(card.getByRole('button', { name: 'Make a new report', exact: true })).toBeEnabled();
	await expect(area('Sleep').locator('.tips li')).toHaveText(tips);
	await snap(page, 'a7-after-reload');
});

test('b: the model is down: urgent warning first, the standard tips and the notice', async ({ page, api, family }) => {
	await setAge(api, family.childId, 42);
	expect((await api.patch('family/settings', { data: { llm: { base_url: 'http://127.0.0.1:9/v1' } } })).ok()).toBeTruthy();
	for (let n = 1; n <= 3; n++)
		await api.post(`children/${family.childId}/entries`, { data: { type: 'play', started_at: `${day(n)}T10:00`, ended_at: `${day(n)}T10:20`, data: { tummy_seconds: 300 } } });
	await api.post(`children/${family.childId}/entries`, { data: { type: 'temperature', started_at: local(Date.now() - 10 * 60_000), data: { celsius: 38.4 } } });
	await page.goto('/reports');
	const { card, waiting } = await makeReport(page);
	await expect(waiting).toBeHidden({ timeout: 60_000 });
	await expect(card.getByText(NOTICE, { exact: true })).toBeVisible();
	const articles = card.getByRole('article');
	await expect(articles.first()).toHaveClass(/urgent/);
	await expect(articles.first()).toContainText('Urgent');
	const play = card.getByRole('article', { name: 'Play and tummy time', exact: true });
	await expect(play.getByRole('heading', { name: 'Ideas to try (standard tips)', exact: true })).toBeVisible();
	await expect(play.locator('.tips li').first()).toHaveText(/^Tummy time can be spread through the day, while Mia is awake\./);
	expect((await checkMarks(play)).length).toBeGreaterThan(0);
	await expect(card.getByText('The 30 minutes are for babies who are not yet mobile. If Mia already moves around, this does not apply.', { exact: true })).toBeVisible();
	await snap(page, 'b1-model-down');
	await snapAt(page, play, 'b2-standard-tips');
});
