import { readFileSync } from 'node:fs';
import { expect, local, shot, test } from './fixtures';

const DAY = 86400_000;

test('History and Reports show a week of data, growth percentile and CSV export', async ({ page, api, family }) => {
	// Seed the last 7 days through the API, the way a week of logging would look.
	const base = `children/${family.childId}/entries`;
	const now = Date.now();
	const day = (n: number) => local(now - n * DAY).slice(0, 10);
	const entries: object[] = [];
	for (let n = 7; n >= 1; n--) {
		const d = day(n);
		if (n > 1) entries.push({ type: 'sleep', started_at: `${d}T19:10`, ended_at: `${day(n - 1)}T05:40`, data: {} });
		entries.push({ type: 'sleep', started_at: `${d}T13:00`, ended_at: `${d}T14:${20 + n}`, data: {} });
		for (const h of ['07', '10', '13', '16', '19']) entries.push({ type: 'bottle', started_at: `${d}T${h}:00`, data: { amount_ml: 110 + n * 5, milk_type: 'Formula' } });
		for (const [h, mode] of [['08', 'pee'], ['12', 'poo'], ['15', 'both'], ['18', 'pee']]) entries.push({ type: 'nappy', started_at: `${d}T${h}:30`, data: { mode } });
	}
	entries.push({ type: 'growth', started_at: `${day(3)}T09:00`, data: { weight_kg: 6.9, height_cm: 64.5, head_cm: 41 } });
	entries.push({ type: 'bottle', started_at: local(now - 5 * 60_000), data: { amount_ml: 90 } });
	for (const data of entries) expect((await api.post(base, { data })).ok(), JSON.stringify(data)).toBeTruthy();

	await page.goto('/history');
	await expect(page.getByRole('heading', { name: 'History' })).toBeVisible();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Bottle/ })).toHaveCount(1);
	await page.getByRole('button', { name: 'Day before' }).click();
	await expect(page.getByText('Yesterday')).toBeVisible();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Bottle/ })).toHaveCount(5);
	await shot(page, '06-history-day');

	await page.getByRole('button', { name: 'List', exact: true }).click();
	await page.getByLabel('Show').selectOption('nappy');
	await expect(page.getByRole('button', { name: /Edit Nappy/ }).first()).toBeVisible();
	await expect(page.getByRole('button', { name: /Edit Bottle/ })).toHaveCount(0);
	await shot(page, '06-history-list');

	await page.getByRole('link', { name: 'Reports' }).click();
	await expect(page.getByRole('img', { name: /Sleep \(hours\) chart/ })).toBeVisible();
	await expect(page.getByRole('img', { name: /Feeds chart/ })).toBeVisible();
	await expect(page.getByRole('img', { name: /Nappies chart/ })).toBeVisible();
	await expect(page.getByText(/Common range for this age/)).toBeVisible();
	await shot(page, '06-reports');

	await expect(page.getByRole('img', { name: 'Growth chart with WHO percentile curves' })).toBeVisible();
	await expect(page.getByText(/6\.9 kg/)).toBeVisible();
	await expect(page.getByText(/th percentile \(WHO\)/)).toBeVisible();
	await page.getByRole('button', { name: 'Length' }).click();
	await expect(page.getByText(/64\.5 cm/)).toBeVisible();
	await page.getByRole('img', { name: 'Growth chart with WHO percentile curves' }).scrollIntoViewIfNeeded();
	await shot(page, '06-reports-growth');

	const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download CSV' }).click()]);
	expect(download.suggestedFilename()).toMatch(/^frecklebubby-mia-.*\.csv$/);
	const csv = readFileSync(await download.path(), 'utf8');
	expect(csv.split('\n')[0]).toContain('id,type,started_at');
	expect(csv).toContain('bottle');
});
