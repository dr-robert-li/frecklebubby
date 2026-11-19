import { expect, local, openTile, request, shot, test } from './fixtures';

test('units and wording change what the parent sees', async ({ page, api, family }) => {
	await api.post(`children/${family.childId}/entries`, { data: { type: 'temperature', started_at: local(Date.now() - 60_000), data: { celsius: 37 } } });

	await page.goto('/settings');
	await shot(page, '08-settings-menu');
	await page.getByRole('link', { name: /Units and wording/ }).click();
	for (const [group, value] of [['Volume', 'oz'], ['Weight', 'lb'], ['Length', 'in'], ['Temperature', '°F'], ['Word for nappy', 'Diaper']]) {
		const btn = page.getByRole('group', { name: group }).getByRole('button', { name: value, exact: true });
		await btn.click();
		await expect(btn).toHaveAttribute('aria-pressed', 'true');
	}
	await shot(page, '08-units');

	await page.getByRole('link', { name: 'Home' }).click();
	await expect(page.getByRole('button', { name: /^Diaper/ })).toBeVisible();
	await expect(page.getByRole('button', { name: /^Nappy/ })).toHaveCount(0);
	await expect(page.getByRole('button', { name: /Edit Temperature/ })).toContainText('98.6 °F');

	const s = await openTile(page, 'Bottle');
	await s.getByLabel('Amount (oz)').fill('4');
	await s.getByRole('button', { name: 'Save' }).click();
	await expect(page.getByRole('button', { name: /Edit Bottle/ })).toContainText('4 oz');
	// stored in ml
	const [bottle] = await (await api.get(`children/${family.childId}/entries?type=bottle`)).json();
	expect(bottle.data.amount_ml).toBeCloseTo(118.3, 0);

	const g = await openTile(page, 'Growth');
	await expect(g.getByLabel('Weight (lb)')).toBeVisible();
	await expect(g.getByLabel('Head (in)')).toBeVisible();
	await shot(page, '08-growth-imperial');
});

test('a parent makes an API token and a script uses it', async ({ page, family, baseURL, email }) => {
	await page.goto('/settings/tokens');
	await page.getByLabel('Name of the new token').fill('Home script');
	await page.getByRole('button', { name: 'Make token' }).click();
	const token = (await page.getByTestId('new-token').innerText()).trim();
	expect(token).toMatch(/^fb_pat_/);
	await expect(page.getByText('Home script')).toBeVisible();
	await shot(page, '08-tokens');

	const script = await request.newContext({ baseURL, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
	const me = await script.get('/api/v1/me');
	expect(me.status()).toBe(200);
	expect((await me.json()).user.email).toBe(email);
	const res = await script.post(`/api/v1/children/${family.childId}/entries`, { data: { type: 'note', started_at: local(), notes: 'From a script' } });
	expect(res.ok()).toBeTruthy();
	await script.dispose();

	await page.getByRole('link', { name: 'Home' }).click();
	await expect(page.getByRole('button', { name: /Edit Note/ })).toContainText('From a script');
});
