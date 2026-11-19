import { expect, local, shot, test } from './fixtures';

test('a parent sets a "remind in" nappy reminder', async ({ page, family }) => {
	await page.goto('/settings/reminders');
	await expect(page.getByText('No reminders yet.')).toBeVisible();
	await page.getByRole('button', { name: 'Add a reminder' }).click();
	const sheet = page.getByRole('dialog');
	await sheet.getByLabel('Remind me about').selectOption('nappy');
	await sheet.getByRole('button', { name: 'Remind in' }).click();
	await sheet.getByLabel('Hours').fill('2');
	await sheet.getByLabel('Minutes').fill('30');
	await sheet.getByLabel('Daytime only').check();
	await shot(page, '10-reminder-sheet');
	await sheet.getByRole('button', { name: 'Save reminder' }).click();

	await expect(sheet).toBeHidden();
	await expect(page.getByText('2 h 30 min after the last one, daytime only')).toBeVisible();
	await shot(page, '10-reminders');

	// "remind at" with days
	await page.getByRole('button', { name: 'Add a reminder' }).click();
	await sheet.getByLabel('Remind me about').selectOption('medicine');
	await sheet.getByRole('button', { name: 'Remind at' }).click();
	await sheet.getByLabel('Time 1', { exact: true }).fill('08:00');
	await sheet.getByRole('button', { name: 'Add a time' }).click();
	await sheet.getByLabel('Time 2', { exact: true }).fill('20:00');
	await sheet.getByRole('button', { name: 'Mon' }).click();
	await sheet.getByRole('button', { name: 'Fri' }).click();
	await sheet.getByRole('button', { name: 'Save reminder' }).click();
	await expect(page.getByText('at 08:00, 20:00 on Mon, Fri')).toBeVisible();

	// turn one off, delete it
	await page.getByRole('checkbox', { name: 'Medicine reminder on' }).uncheck();
	await expect(page.getByRole('checkbox', { name: 'Medicine reminder on' })).not.toBeChecked();
	await page.getByRole('button', { name: 'Delete Medicine reminder' }).click();
	await expect(page.getByText('at 08:00, 20:00 on Mon, Fri')).toBeHidden();
});

test('a due reminder shows as an unread notification', async ({ page, api, family }) => {
	test.setTimeout(150_000);
	await api.post(`children/${family.childId}/entries`, { data: { type: 'bottle', started_at: local(Date.now() - 10 * 60_000), data: { amount_ml: 100 } } });
	expect((await api.post(`children/${family.childId}/reminders`, { data: { type: 'bottle', mode: 'in', interval_minutes: 1 } })).ok()).toBeTruthy();

	await page.goto('/');
	// The server checks reminders once a minute; the app polls status every 15 s.
	const bell = page.getByRole('link', { name: /Notifications, 1 unread/ });
	await expect(bell).toBeVisible({ timeout: 100_000 });
	await shot(page, '10-badge');
	await bell.click();
	await expect(page.getByRole('button', { name: /unread/ })).toHaveCount(1);
	await shot(page, '10-notifications');
	await page.getByRole('button', { name: 'Mark all read' }).click();
	await expect(page.getByRole('button', { name: /unread/ })).toHaveCount(0);

	await page.goto('/settings/notifications');
	await page.getByRole('button', { name: 'Send test notification' }).click();
	await expect(page.getByText('No device has notifications on')).toBeVisible();
	await shot(page, '10-push-settings');
});
