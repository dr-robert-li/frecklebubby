import { expect, openTile, shot, test } from './fixtures';

test('a second carer joins by invite and sees the running timer', async ({ page, family, browser, baseURL }) => {
	const carer = `carer-${Date.now()}@example.com`;

	// Owner invites the carer and starts a sleep timer.
	await page.goto('/settings/family');
	await page.getByLabel('Invite a carer by email').fill(carer);
	await page.getByRole('button', { name: 'Invite', exact: true }).click();
	await expect(page.getByText(carer)).toBeVisible();
	await shot(page, '07-invite');
	await page.getByRole('link', { name: 'Home' }).click();
	const sheet = await openTile(page, 'Sleep');
	await sheet.getByRole('button', { name: 'Start sleep timer' }).click();
	await expect(page.getByRole('region', { name: 'Sleep timer' })).toBeVisible();

	// The carer signs in on another phone.
	const ctx = await browser.newContext({ ...test.info().project.use, baseURL, recordVideo: { dir: test.info().outputPath('carer-video') } });
	await ctx.addInitScript((e) => localStorage.setItem('fb.devUser', e), carer);
	const phone2 = await ctx.newPage();
	await phone2.goto('/');
	await expect(phone2.getByRole('button', { name: /Child: Mia/ })).toBeVisible();
	const timer = phone2.getByRole('region', { name: 'Sleep timer' });
	await expect(timer).toBeVisible();
	await expect(timer.getByText(/Running/)).toBeVisible();
	await shot(phone2, '07-carer-sees-timer');

	// The carer stops it; the owner's screen follows on the next refresh (focus or poll).
	await timer.getByRole('button', { name: 'Stop and save' }).click();
	await expect(timer).toBeHidden();
	await page.evaluate(() => window.dispatchEvent(new Event('focus')));
	await expect(page.getByRole('region', { name: 'Sleep timer' })).toBeHidden();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Sleep/ })).toBeVisible();

	await phone2.goto('/settings/family');
	await expect(phone2.getByText('Only the family owner can invite carers.')).toBeVisible();
	await ctx.close();
});
