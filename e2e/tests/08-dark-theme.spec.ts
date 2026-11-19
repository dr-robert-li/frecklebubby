import { expect, local, openTile, shot, test } from './fixtures';

test('night theme for feeds in the dark, on every screen', async ({ page, api, family }) => {
	const base = `children/${family.childId}/entries`;
	await api.post(base, { data: { type: 'bottle', started_at: local(Date.now() - 30 * 60_000), data: { amount_ml: 120, milk_type: 'Breast Milk' } } });
	await api.post(base, { data: { type: 'nappy', started_at: local(Date.now() - 20 * 60_000), data: { mode: 'both', color: 'yellow' } } });
	await api.post(`children/${family.childId}/timers/nursing/start`, { data: { side: 'right' } });

	await page.goto('/settings/appearance');
	await page.getByRole('button', { name: 'Night' }).click();
	await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
	const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
	expect(bg).toBe('rgb(22, 20, 30)');
	await shot(page, '09-dark-appearance');

	await page.getByRole('link', { name: 'Home' }).click();
	await expect(page.getByRole('region', { name: 'Nursing timer' })).toBeVisible();
	await shot(page, '09-dark-home');
	await shot(page, '09-dark-home-bottom', true);
	await openTile(page, 'Bottle');
	await shot(page, '09-dark-sheet');
	await page.getByRole('button', { name: 'Close' }).click();

	// the choice stays after a reload
	await page.reload();
	await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

	for (const [link, name] of [['History', '09-dark-history'], ['Reports', '09-dark-reports'], ['Assistant', '09-dark-assistant'], ['Settings', '09-dark-settings']]) {
		await page.getByRole('link', { name: link }).click();
		await expect(page.getByRole('heading', { name: link, level: 1 })).toBeVisible();
		await shot(page, name);
	}
});

test('auto theme follows the device', async ({ page, family }) => {
	await page.emulateMedia({ colorScheme: 'dark' });
	await page.goto('/');
	await expect(page.getByRole('button', { name: /^Sleep/ })).toBeVisible();
	expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(22, 20, 30)');
});
