import { expect, shot, test, todayAgo } from './fixtures';

test('a parent fixes the time of an entry and deletes another', async ({ page, api, family }) => {
	for (const [type, data, t] of [['bottle', { amount_ml: 90 }, 20], ['nappy', { mode: 'pee' }, 21]] as const)
		expect((await api.post(`children/${family.childId}/entries`, { data: { type, started_at: todayAgo(t), data } })).ok()).toBeTruthy();

	await page.goto('/');
	const timeline = page.getByRole('list', { name: 'Timeline' });
	const bottle = timeline.getByRole('button', { name: /Edit Bottle/ });
	await bottle.click();

	const sheet = page.getByRole('dialog');
	await expect(sheet.getByRole('heading', { name: 'Edit bottle' })).toBeVisible();
	const newTime = todayAgo(10);
	await sheet.getByLabel('Time', { exact: true }).fill(newTime);
	await sheet.getByLabel('Amount (ml)').fill('100');
	await shot(page, '05-edit-sheet');
	await sheet.getByRole('button', { name: 'Save' }).click();
	await expect(sheet).toBeHidden();
	await expect(bottle).toContainText(newTime.slice(11));
	await expect(bottle).toContainText('100 ml');

	await timeline.getByRole('button', { name: /Edit Nappy/ }).click();
	await sheet.getByRole('button', { name: 'Delete entry' }).click();
	await shot(page, '05-delete-confirm', true);
	await sheet.getByRole('button', { name: 'Yes, delete' }).click();
	await expect(timeline.getByRole('button', { name: /Edit Nappy/ })).toHaveCount(0);
	await expect(timeline.getByRole('listitem')).toHaveCount(1);
});
