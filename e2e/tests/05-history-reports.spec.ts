import { readFileSync } from 'node:fs';
import { expect, local, shot, test, todayAgo } from './fixtures';

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
	entries.push({ type: 'bottle', started_at: todayAgo(5), data: { amount_ml: 90 } });
	for (const data of entries) expect((await api.post(base, { data })).ok(), JSON.stringify(data)).toBeTruthy();

	await page.goto('/history');
	await expect(page.getByRole('heading', { name: 'History' })).toBeVisible();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Bottle/ })).toHaveCount(1);
	await page.getByRole('button', { name: 'Day before' }).click();
	await expect(page.getByText('Yesterday')).toBeVisible();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Bottle/ })).toHaveCount(5);
	await shot(page, '06-history-day');

	// the day shows the newest entry first
	const times = await page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Bottle/ }).evaluateAll((l) => l.map((b) => b.getAttribute('aria-label')!.slice(-5)));
	expect(times).toEqual([...times].sort().reverse());
	expect(times.length).toBe(5);

	// Week: one row for each of the last 7 days to the selected day, the newest first, with totals; a row opens its day
	await page.getByRole('button', { name: 'Week', exact: true }).click();
	const week = page.getByRole('list', { name: 'Week' });
	await expect(week.getByRole('listitem')).toHaveCount(7);
	await expect(week.getByRole('listitem').first()).toContainText('Feeds 5 · Nappies 4');
	await expect(week.getByRole('listitem').first()).toContainText(/Sleep \d+ h/);
	await shot(page, '06-history-week');
	await page.getByRole('button', { name: 'Month', exact: true }).click();
	const month = page.getByRole('list', { name: 'Month' });
	await expect(month.getByRole('listitem')).toHaveCount(30);
	await shot(page, '06-history-month');
	await month.getByRole('listitem').nth(2).getByRole('button').click();
	await expect(page.getByRole('button', { name: 'Day', exact: true })).toHaveAttribute('aria-pressed', 'true');
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Bottle/ })).toHaveCount(5);

	await page.getByRole('button', { name: 'List', exact: true }).click();
	await page.getByText(/^Types:/).click();
	await page.getByRole('button', { name: 'Deselect all' }).click();
	await expect(page.getByText('Select one type or more.')).toBeVisible();
	await page.getByRole('checkbox', { name: 'Nappy' }).check();
	await expect(page.getByRole('button', { name: /Edit Nappy/ }).first()).toBeVisible();
	await expect(page.getByRole('button', { name: /Edit Bottle/ })).toHaveCount(0);
	await page.getByRole('checkbox', { name: 'Bottle' }).check();
	await expect(page.getByText('Types: 2 of')).toBeVisible();
	await expect(page.getByRole('button', { name: /Edit Bottle/ }).first()).toBeVisible();

	// order by the logged volume: the largest bottle is first, then the smallest is first
	await page.getByLabel('Order by').selectOption('volume');
	const first = page.getByRole('list', { name: 'Timeline' }).getByRole('listitem').first();
	await expect(first).toContainText('145 ml');
	await page.getByText(/^Types:/).click(); // close the type list
	await shot(page, '06-history-list-volume');
	await expect(page.getByRole('button', { name: /Edit Nappy/ })).toHaveCount(0);
	await page.getByRole('button', { name: 'Smallest first' }).click();
	await expect(first).toContainText('90 ml');
	// a range of days: the list shows only these days together, with their total
	await page.getByText(/^Days:/).click();
	await page.getByLabel('First day').fill(day(1));
	await expect(page.getByText('(1 day)')).toBeVisible();
	await page.getByLabel('Last day').fill(day(0));
	await expect(page.getByText('(2 days)')).toBeVisible();
	await expect(page.getByText('6 entries in 2 days. Total: 665 ml')).toBeVisible();
	await expect(page.getByRole('button', { name: /Edit Bottle/ })).toHaveCount(6);
	// a range can have 180 days at most: the other day moves
	await page.getByLabel('First day').fill(day(300));
	await expect(page.getByText('(180 days)')).toBeVisible();
	await expect(page.getByLabel('Last day')).toHaveValue(day(121));
	await page.getByRole('button', { name: 'Last 7 days' }).click();
	await expect(page.getByText('(7 days)')).toBeVisible();
	await page.getByText(/^Days:/).click();
	await shot(page, '06-history-list-days');
	await page.getByText(/^Days:/).click();
	await page.getByRole('button', { name: 'All days' }).click();
	await expect(page.getByText('Days: all')).toBeVisible();
	await page.getByLabel('Order by').selectOption('time');
	await page.getByRole('button', { name: 'Newest first' }).click();
	await shot(page, '06-history-list');

	await page.getByRole('link', { name: 'Reports' }).click();
	await expect(page.getByRole('img', { name: /Sleep \(hours\) chart/ })).toBeVisible();
	await expect(page.getByRole('img', { name: /Feeds chart/ })).toBeVisible();
	await expect(page.getByRole('img', { name: /Nappies chart/ })).toBeVisible();
	await expect(page.getByText(/Common range for this age/)).toBeVisible();
	await expect(page.getByText(/^Average \d+(\.\d)? h$/)).toBeVisible();
	await expect(page.getByText('Average 4.4', { exact: true })).toBeVisible(); // feeds: 5 a day on 6 days and 1 today
	await page.getByRole('button', { name: 'Month', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Earlier month' })).toBeVisible();
	await expect(page.getByRole('img', { name: /Feeds chart/ })).toBeVisible();
	await shot(page, '06-reports-month');
	await page.getByRole('button', { name: 'Week', exact: true }).click();
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
