// M9 new logging: play with tummy time, nappy details, confined time with the 1-hour note and the 2-hour warning.
// Project `m9` (main server, no model).
import type { Page } from '@playwright/test';
import { expect, local, openTile, setAge, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm9');
const ago = (min: number) => local(Date.now() - min * 60_000);
const DAY = 86400_000;

test('play with the tummy time toggle, then the timeline and the report', async ({ page, api, family }) => {
	// Yesterday: 40 min of play with 25 min of tummy time, so the report has a full bar.
	const y = local(Date.now() - DAY).slice(0, 10);
	expect((await api.post(`children/${family.childId}/entries`, {
		data: { type: 'play', started_at: `${y}T09:00`, ended_at: `${y}T09:40`, data: { kind: 'indoor', tummy_seconds: 1500 } }
	})).ok()).toBeTruthy();

	await page.goto('/');
	const s = await openTile(page, 'Play');
	await snap(page, '01-play-sheet');
	await s.getByRole('button', { name: 'Start play timer' }).click();
	await expect(s).toBeHidden();
	const card = page.getByRole('region', { name: 'Play timer' });
	const tummy = card.getByRole('button', { name: /^Tummy time/ });
	await expect(tummy).toHaveAttribute('aria-pressed', 'false');
	await tummy.click();
	await expect(tummy).toHaveAttribute('aria-pressed', 'true');
	await expect(card.getByRole('timer', { name: 'Tummy time' })).toHaveText(/^0:0[2-9]$/, { timeout: 15_000 });
	await snap(page, '02-play-tummy-on');
	await tummy.click();
	await expect(tummy).toHaveAttribute('aria-pressed', 'false');
	const stopped = await card.getByRole('timer', { name: 'Tummy time' }).innerText();
	await page.waitForTimeout(1500);
	await expect(card.getByRole('timer', { name: 'Tummy time' })).toHaveText(stopped); // the tummy clock stops
	await snap(page, '03-play-tummy-off');
	await card.getByRole('button', { name: 'Stop and save' }).click();
	await expect(card).toBeHidden();

	const row = page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Play/ });
	await expect(row).toContainText(/Tummy time \d+ s/);
	await snap(page, '04-play-timeline', true);
	await row.click();
	const edit = page.getByRole('dialog');
	await edit.getByRole('button', { name: 'Outdoor' }).click();
	await edit.getByLabel('Tummy time (min)').fill('3');
	await edit.getByRole('button', { name: 'Save' }).click();
	await expect(edit).toBeHidden();
	await expect(row).toContainText('Outdoor');
	await expect(row).toContainText('Tummy time 3 min');

	await page.getByRole('link', { name: 'Reports' }).click();
	const chart = page.getByRole('img', { name: /Play per day \(minutes\) chart/ });
	await expect(chart).toBeVisible();
	await expect(page.locator('figure').filter({ hasText: 'Play per day' }).getByText('30 min tummy time')).toBeVisible();
	await expect(page.getByRole('table').filter({ hasText: 'Play per day' })).toContainText('25 min');
	await expect(page.getByRole('link', { name: /^WHO/ })).toBeVisible();
	await chart.scrollIntoViewIfNeeded();
	await snap(page, '05-play-report');
});

test('nappy: quick log in 2 taps; rash, air time and wee details, then edit', async ({ page, family }) => {
	await page.goto('/');
	// Quick log: tile, then Save. The details stay closed.
	let s = await openTile(page, 'Nappy');
	await expect(s.getByText('More details')).toBeVisible();
	await expect(s.getByLabel('Nappy rash')).toBeHidden();
	await snap(page, '06-nappy-quick');
	await s.getByRole('button', { name: 'Save' }).click();
	await expect(s).toBeHidden();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Nappy/ })).toContainText('Wet');

	s = await openTile(page, 'Nappy');
	await s.getByText('More details').click();
	await s.getByRole('button', { name: 'Dark yellow' }).click();
	await s.getByRole('button', { name: 'Cloudy' }).click();
	await s.getByLabel('Strong smell').check();
	await s.getByLabel('Nappy rash').check();
	await s.getByRole('button', { name: 'Mild' }).click();
	await s.getByRole('group', { name: /Air time.*quick choice/ }).getByRole('button', { name: '10 min' }).click();
	await expect(s.getByLabel('Air time (nappy off) (min)')).toHaveValue('10');
	await snap(page, '07-nappy-details');
	await s.getByRole('button', { name: 'Save' }).click();

	// Right after a rash: the NHS advice with its source, and the app tip.
	await expect(s.getByRole('heading', { name: 'Nappy rash' })).toBeVisible();
	await expect(s.getByRole('status')).toContainText('leave nappies off when possible');
	await expect(s.getByRole('status')).toContainText('little tummy time');
	await expect(s.getByRole('button', { name: /\[1\] NHS/ })).toBeVisible();
	await snap(page, '08-nappy-rash-advice');
	await s.getByRole('button', { name: 'Done' }).click();
	await expect(s).toBeHidden();

	const row = page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Nappy/ }).first();
	await expect(row).toContainText('Wee dark yellow');
	await expect(row).toContainText('Rash (mild)');
	await expect(row).toContainText('Air time 10 min');
	await snap(page, '09-nappy-timeline', true);

	await row.click();
	const edit = page.getByRole('dialog');
	await expect(edit.getByLabel('Nappy rash')).toBeChecked(); // details open when the entry has them
	await expect(edit.getByRole('button', { name: 'Cloudy' })).toHaveAttribute('aria-pressed', 'true');
	await edit.getByLabel('Air time (nappy off) (min)').fill('15');
	await snap(page, '10-nappy-edit');
	await edit.getByRole('button', { name: 'Save' }).click();
	await expect(edit.getByRole('heading', { name: 'Nappy rash' })).toBeVisible();
	await edit.getByRole('button', { name: 'Done' }).click();
	await expect(row).toContainText('Air time 15 min');
	void family;
});

test('confined: a car seat timer with an earlier start shows the 1-hour note, then the 2-hour warning, and the bell', async ({ page, family }) => {
	test.setTimeout(240_000);
	await page.goto('/');
	const s = await openTile(page, 'Confined');
	await s.getByRole('button', { name: 'Car seat' }).click();
	await snap(page, '11-confined-sheet');
	await s.getByRole('button', { name: 'Start confined timer' }).click();
	await expect(s).toBeHidden();
	const card = page.getByRole('region', { name: 'Car seat timer' });
	await expect(card).toBeVisible();
	await expect(card.getByRole('status')).toHaveCount(0);

	// The parent forgot to start it: move the start to 65 minutes ago.
	await card.getByRole('button', { name: 'Change' }).click();
	await card.getByLabel('Start time').fill(ago(65));
	await card.getByRole('button', { name: 'Save', exact: true }).click();
	const level = card.getByRole('status');
	await expect(level).toContainText('Good to know');
	await expect(level).toContainText('Mia: in the car seat for 1 hour');
	await expect(level).toContainText('not restrained for more than 1 hour at a time');
	await expect(level.getByRole('button', { name: /\[1\]/ })).toBeVisible();
	await snap(page, '12-confined-note');

	await card.getByRole('button', { name: 'Change' }).click();
	await card.getByLabel('Start time').fill(ago(125));
	await card.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(level).toContainText('Time for a break');
	await expect(level).toContainText('take a break every 2 to 3 hours on a day trip');
	await expect(level.getByRole('button', { name: /\[1\]/ })).toBeVisible();
	await snap(page, '13-confined-warning');

	// The server checks each 60 s; the app reads the unread count every 15 s. The warning comes with or after the
	// note, so 2 or more unread means both were sent (a check between the two start changes can add a second note).
	const bell = page.getByRole('link', { name: /^Notifications, ([2-9]|\d\d+) unread$/ });
	await expect(bell).toBeVisible({ timeout: 150_000 });
	await bell.click();
	await expect(page.getByRole('button', { name: /time for a break/ })).toHaveCount(1);
	await expect(page.getByRole('button', { name: /in the car seat for 1 hour/ }).first()).toBeVisible();
	await snap(page, '14-confined-notifications');
	void family;
});

test('confined: a 2-year-old gets the 1-hour note and not the 2-hour warning', async ({ page, api, family }) => {
	test.setTimeout(240_000);
	await setAge(api, family.childId, 730);
	expect((await api.post(`children/${family.childId}/timers/confined/start`, { data: { at: ago(130), device: 'pram' } })).ok()).toBeTruthy();
	await page.goto('/');
	const card = page.getByRole('region', { name: 'Pram timer' });
	const level = card.getByRole('status');
	await expect(level).toContainText('Mia: in the pram for 1 hour');
	await expect(card).not.toContainText('Time for a break');
	await snap(page, '15-confined-2-years');

	await expect(page.getByRole('link', { name: 'Notifications, 1 unread' })).toBeVisible({ timeout: 150_000 });
	await page.getByRole('link', { name: 'Notifications, 1 unread' }).click();
	await expect(page.getByRole('button', { name: /in the pram for 1 hour/ })).toHaveCount(1);
	await expect(page.getByRole('button', { name: /time for a break/ })).toHaveCount(0);
	await snap(page, '16-confined-2-years-bell');
});
