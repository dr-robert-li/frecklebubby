// M4 proof: a reminder set in the UI fires on the server's reminder tick and shows as an unread notification;
// push subscription as far as headless Chromium allows. Project `m4`.
import type { Page } from '@playwright/test';
import { expect, openTile, shot, test, todayAgo } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm4');

test('a nappy reminder set in the app fires and the parent reads it', async ({ page, family }) => {
	test.setTimeout(240_000);
	await page.goto('/settings/reminders');
	await page.getByRole('button', { name: 'Add a reminder' }).click();
	const sheet = page.getByRole('dialog');
	await sheet.getByLabel('Remind me about').selectOption('nappy');
	await sheet.getByRole('button', { name: 'Remind in' }).click();
	await sheet.getByLabel('Hours').fill('0');
	await sheet.getByLabel('Minutes').fill('1');
	await snap(page, 'g1-reminder-sheet');
	await sheet.getByRole('button', { name: 'Save reminder' }).click();
	await expect(sheet).toBeHidden();
	await snap(page, 'g2-reminders');

	// a nappy 10 minutes ago, so the reminder is due now
	await page.getByRole('link', { name: 'Home' }).click();
	const s = await openTile(page, 'Nappy');
	await s.getByLabel('Time', { exact: true }).fill(todayAgo(10));
	await s.getByRole('button', { name: 'Wee', exact: true }).click();
	await s.getByRole('button', { name: 'Save' }).click();
	await expect(s).toBeHidden();

	// The server checks reminders every 60 s; the app reads the unread count every 15 s.
	const bell = page.getByRole('link', { name: 'Notifications, 1 unread' });
	await expect(bell).toBeVisible({ timeout: 150_000 });
	await snap(page, 'g3-badge');
	await bell.click();
	const note = page.getByRole('button', { name: /, unread$/ });
	await expect(note).toHaveCount(1);
	await expect(note).toContainText(/nappy/i);
	await snap(page, 'g4-notifications');
	await note.click();
	await expect(page.getByRole('button', { name: /, unread$/ })).toHaveCount(0);
	await expect(page.getByRole('link', { name: 'Notifications', exact: true })).toBeVisible({ timeout: 30_000 });
	await snap(page, 'g5-read');
});

test('push: permission granted, subscribe and send a test notification', async ({ page, context, baseURL, family }) => {
	await context.grantPermissions(['notifications'], { origin: baseURL });
	await page.goto('/settings/notifications');
	// Headless Chromium reports Notification.permission "denied" even after grantPermissions, so the status line can
	// say "Blocked"; the button still asks the browser.
	const before = await page.getByText(/^Status:/).innerText();
	const perm = await page.evaluate(async () => [Notification.permission, (await navigator.permissions.query({ name: 'notifications' })).state]);
	test.info().annotations.push({ type: 'permission', description: `${before}; Notification.permission=${perm[0]}; permissions.query=${perm[1]}` });
	await page.getByRole('button', { name: 'Turn on notifications' }).click();
	// Headless Chromium has no push service: subscribe() may fail. Record what the parent sees either way.
	const on = page.getByText('Status: On');
	const err = page.getByRole('alert');
	await expect(on.or(err)).toBeVisible({ timeout: 30_000 });
	await snap(page, 'g6-push-subscribe');
	const subscribed = await on.isVisible();
	test.info().annotations.push({ type: 'push', description: subscribed ? 'subscribed' : `not subscribed: ${await err.innerText()}` });
	await page.getByRole('button', { name: 'Send test notification' }).click();
	await expect(page.getByText(subscribed ? /^Test sent to 1 device/ : 'No device has notifications on')).toBeVisible();
	await snap(page, 'g7-push-test');
});
