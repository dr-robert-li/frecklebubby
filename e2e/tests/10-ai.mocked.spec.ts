// AI, knowledge and import endpoints are not built yet: these routes are mocked to the contract in
// .planning/API_NOTES.md. Everything else in these tests runs against the real API.
import type { Page, Route } from '@playwright/test';
import { expect, local, shot, test } from './fixtures';

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
const NHS = { n: 1, title: 'Baby sleep: how much sleep does a baby need', publisher: 'NHS', url: 'https://www.nhs.uk/baby/sleep/', year: 2024, kind: 'bundled', licence: 'OGL v3' };
const RCN = { n: 2, title: 'Sleep: babies 3-12 months', publisher: 'Raising Children Network', url: 'https://raisingchildren.net.au/babies/sleep', kind: 'link' };

async function mockAll(page: Page) {
	await page.route('**/api/v1/children/*/assistant/messages', (r) => (r.request().method() === 'DELETE' ? r.fulfill({ status: 204 }) : json(r, [])));
	await page.route('**/api/v1/children/*/assistant/chat', (r) =>
		r.fulfill({
			status: 200,
			contentType: 'text/event-stream',
			body: [
				['token', { text: 'Most babies of 5 months sleep 12 to 15 hours a day ' }],
				['token', { text: '[1]. A steady bedtime routine helps [2].' }],
				['citations', { citations: [NHS, RCN] }],
				['done', { message_id: 42 }]
			].map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')
		})
	);
	await page.route('**/api/v1/children/*/insights', (r) =>
		json(r, [
			{ kind: 'sleep_total', severity: 'info', title: 'Sleep is in the common range', body: 'Mia slept 13 h a day on average this week.', citations: [NHS] },
			{ kind: 'fever', severity: 'urgent', title: 'High temperature', body: 'A temperature of 38 °C or more under 3 months needs a doctor now.', citations: [NHS] },
			{ kind: 'wet', severity: 'attention', title: 'Fewer wet nappies today', body: 'Watch for signs of dehydration.', citations: [] }
		])
	);
	let plan: unknown = null;
	await page.route('**/api/v1/children/*/sleep/plan', async (r) => {
		if (r.request().method() === 'POST')
			plan = {
				id: 3, created_at: new Date().toISOString(), summary: 'Three naps and bedtime at 18:45.',
				schedule: [
					{ time: '06:30', kind: 'wake', label: 'Wake up' }, { time: '08:15', kind: 'nap', label: 'Nap 1', note: 'About 1 hour' },
					{ time: '12:00', kind: 'nap', label: 'Nap 2' }, { time: '18:45', kind: 'bedtime', label: 'Bedtime' }
				],
				advice: [{ text: 'Keep the room dark for naps.', cites: [1] }],
				citations: [NHS]
			};
		// M15: POST starts a job (202); the page polls .../job, then reads the plan.
		await (r.request().method() === 'POST' ? json(r, { status: 'running', error: null }, 202) : json(r, plan));
	});
	await page.route('**/api/v1/children/*/sleep/plan/job', (r) => json(r, { status: 'done', error: null }));
}

test('the parent asks the assistant and opens a source', async ({ page, family }) => {
	await mockAll(page);
	await page.goto('/assistant');
	await page.getByLabel('Your question').fill('How much should she sleep?');
	await page.getByRole('button', { name: 'Send' }).click();
	await expect(page.getByText(/Most babies of 5 months sleep 12 to 15 hours/)).toBeVisible();
	await expect(page.getByText('General information, not medical advice.')).toBeVisible();
	await shot(page, '11-assistant-chat');
	await page.getByRole('button', { name: '[2] Raising Children Network' }).click();
	const src = page.getByRole('dialog');
	await expect(src.getByText('Sleep: babies 3-12 months')).toBeVisible();
	await expect(src.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', RCN.url);
	await shot(page, '11-source');
	await page.getByRole('button', { name: 'Close' }).click();

	await page.getByRole('tab', { name: 'Insights' }).click();
	const cards = page.getByRole('article');
	await expect(cards).toHaveCount(3);
	await expect(cards.first()).toContainText('High temperature');
	await expect(cards.first()).toContainText('Urgent');
	await expect(cards.first()).toHaveClass(/urgent/);
	await expect(page.getByText('General information, not medical advice.')).toBeVisible();
	await shot(page, '11-insights');

	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	await expect(page.getByRole('region', { name: 'Day and night plan' }).locator('.schedule li.wake')).toBeVisible(); // calculated, no model
	await page.getByRole('button', { name: 'Write advice for this plan' }).click();
	await expect(page.getByText('Three naps and bedtime at 18:45.')).toBeVisible();
	await expect(page.getByText('Keep the room dark for naps.')).toBeVisible();
	await shot(page, '11-sleep-plan');

	// milestones are real (the endpoint exists)
	await page.getByRole('tab', { name: 'Milestones' }).click();
	const first = page.getByRole('button', { name: /^Mark done:/ }).first();
	await expect(first).toBeVisible();
	await shot(page, '11-milestones');
	const before = await page.getByRole('button', { name: /^Mark done:/ }).count();
	await first.click();
	await expect(page.getByRole('button', { name: /^Mark done:/ })).toHaveCount(before - 1);
});

test('the parent logs by plain words, removes one proposal and confirms', async ({ page, family }) => {
	let committed: any = null;
	await page.route('**/api/v1/children/*/nl/parse', (r) =>
		json(r, {
			message: 'I found 2 things to log.',
			proposals: [
				{ action: 'entry', type: 'bottle', started_at: local(Date.now() - 20 * 60_000), data: { amount_ml: 120, milk_type: 'Formula' }, summary: 'Bottle – 120 ml formula' },
				{ action: 'entry', type: 'nappy', started_at: local(Date.now() - 15 * 60_000), data: { mode: 'pee' }, summary: 'Nappy – wee' }
			]
		})
	);
	await page.route('**/api/v1/children/*/nl/commit', (r) => ((committed = r.request().postDataJSON()), json(r, { created: [{ id: 1 }], timers: [] })));

	await page.goto('/');
	await page.getByRole('textbox', { name: 'Tell me what happened' }).fill('120 ml formula 20 min ago and a wet nappy');
	await page.getByRole('button', { name: 'Read my words' }).click();
	await expect(page.getByText('I found 2 things to log.')).toBeVisible();
	await shot(page, '11-nl-preview');
	await page.getByRole('button', { name: 'Remove Nappy – wee' }).click();
	await page.getByRole('button', { name: 'Save this' }).click();
	await expect(page.getByText('Saved 1 item')).toBeVisible();
	expect(committed.proposals).toHaveLength(1);
	expect(committed.proposals[0].type).toBe('bottle');
});

test('AI features fail softly when the model is down', async ({ page, family }) => {
	const down = (r: Route) => json(r, { detail: 'The assistant is not available now.' }, 503);
	await page.route('**/api/v1/children/*/nl/parse', down);
	await page.route('**/api/v1/children/*/assistant/**', down);
	await page.route('**/api/v1/children/*/insights', (r) => json(r, { detail: 'Not found.' }, 404));
	await page.route('**/api/v1/children/*/sleep/plan', down);

	await page.goto('/');
	await page.getByRole('textbox', { name: 'Tell me what happened' }).fill('bottle 100 ml');
	await page.getByRole('button', { name: 'Read my words' }).click();
	await expect(page.getByRole('alert')).toHaveText('The assistant is not available now.');
	// trackers still work
	await page.getByRole('button', { name: /^Bottle/ }).click();
	await page.getByRole('dialog').getByLabel('Amount (ml)').fill('100');
	await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
	await expect(page.getByRole('button', { name: /Edit Bottle/ })).toContainText('100 ml');

	await page.goto('/assistant');
	await page.getByLabel('Your question').fill('Is she eating enough?');
	await page.getByRole('button', { name: 'Send' }).click();
	await expect(page.getByRole('alert')).toHaveText('The assistant is not available now.');
	await shot(page, '11-assistant-down');
	await page.getByRole('tab', { name: 'Insights' }).click();
	await expect(page.getByText('Insights are not available now.')).toBeVisible();
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	await expect(page.getByText('The assistant is not available now.')).toBeVisible();
});

test('settings: model test, knowledge upload and Huckleberry import', async ({ page, family }) => {
	await page.route('**/api/v1/family/settings/llm-test', (r) => json(r, { ok: true, detail: 'The model answered in 1.2 s.', model: 'qwen3-4b' }));
	const sources = [
		{ id: 1, kind: 'bundled', title: 'Baby sleep', author: null, publisher: 'NHS', url: 'https://www.nhs.uk/', licence: 'OGL v3', year: 2024, own: false },
		{ id: 2, kind: 'link', title: 'Healthy Sleep Habits, Happy Child', author: 'Marc Weissbluth', publisher: 'Ballantine', url: null, licence: null, year: 2015, own: false }
	];
	await page.route('**/api/v1/knowledge/sources', (r) => json(r, sources));
	await page.route('**/api/v1/knowledge/uploads', (r) => {
		const s = { id: 9, kind: 'upload', title: 'Our GP notes', author: null, publisher: null, url: null, licence: null, year: null, own: true };
		sources.push(s);
		return json(r, { ...s, chunks: 4 });
	});
	await page.route('**/api/v1/knowledge/sources/9', (r) => (sources.pop(), r.fulfill({ status: 204 })));
	let polls = 0;
	await page.route('**/api/v1/import/huckleberry', (r) => json(r, { job_id: 7 }));
	await page.route('**/api/v1/import/jobs/7', (r) =>
		json(r, polls++ < 1
			? { id: 7, status: 'running', progress: { stage: 'sleep', children: 1, entries: { sleep: 120 }, skipped: 0 }, error: null }
			: { id: 7, status: 'done', progress: { stage: 'done', children: 1, entries: { sleep: 412, feed: 950, diaper: 610 }, skipped: 3 }, error: null })
	);

	await page.goto('/settings/ai');
	await page.getByRole('button', { name: 'Test connection' }).click();
	await expect(page.getByText(/Connected\. The model answered in 1\.2 s\. Model: qwen3-4b/)).toBeVisible();
	await shot(page, '12-ai-settings');

	await page.goto('/settings/knowledge');
	await expect(page.getByText('Healthy Sleep Habits, Happy Child')).toBeVisible();
	await page.getByLabel(/Choose a file/).setInputFiles({ name: 'gp-notes.md', mimeType: 'text/markdown', buffer: Buffer.from('# GP notes\nSleep on the back.') });
	await expect(page.getByRole('listitem').filter({ hasText: 'Our GP notes' })).toBeVisible();
	await shot(page, '12-knowledge');
	await page.getByRole('button', { name: 'Delete Our GP notes' }).click();
	await expect(page.getByRole('listitem').filter({ hasText: 'Our GP notes' })).toHaveCount(0);

	await page.goto('/settings/import');
	await page.getByLabel('Huckleberry email').fill('me@example.com');
	await page.getByLabel('Huckleberry password').fill('secret');
	await page.getByRole('button', { name: 'Start import' }).click();
	await expect(page.getByRole('heading', { name: 'Import complete' })).toBeVisible();
	await expect(page.getByText('1 child · 1972 entries · 3 skipped')).toBeVisible();
	await expect(page.getByLabel('Huckleberry password')).toHaveValue('');
	await shot(page, '12-import', true);
});

test('import and uploads say so when the server does not have them yet', async ({ page, family }) => {
	await page.route('**/api/v1/import/huckleberry', (r) => json(r, { detail: 'Not found.' }, 404));
	await page.goto('/settings/import');
	await page.getByLabel('Huckleberry email').fill('me@example.com');
	await page.getByLabel('Huckleberry password').fill('secret');
	await page.getByRole('button', { name: 'Start import' }).click();
	await expect(page.getByRole('alert')).toHaveText('Import is not available on this server yet.');
});
