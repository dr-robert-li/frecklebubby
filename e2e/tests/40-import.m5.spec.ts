// M5 proof: Huckleberry import through the UI against the built-in fake Huckleberry (HUCKLEBERRY_FAKE=1,
// dev mode only): 2 children (Mia, Leo), 60 rows. Project `m5`.
import type { APIRequestContext, Page } from '@playwright/test';
import { expect, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm5');

async function entryCount(api: APIRequestContext) {
	const kids: { id: number; name: string }[] = await (await api.get('children')).json();
	let n = 0;
	for (const k of kids) n += (await (await api.get(`children/${k.id}/entries?limit=1000`)).json()).length;
	return { names: kids.map((k) => k.name).sort(), n };
}

async function runImport(page: Page, password: string) {
	await page.getByLabel('Huckleberry email').fill('parent@example.com');
	await page.getByLabel('Huckleberry password').fill(password);
	await page.getByRole('button', { name: 'Start import' }).click();
}

test('h: a parent copies two children from Huckleberry, and a second run makes no copies', async ({ page, api, family }) => {
	// The family already has its own child; rename it so the imported Mia is easy to tell apart.
	await api.patch(`children/${family.childId}`, { data: { name: 'Ada' } });

	await page.goto('/settings/import');
	await runImport(page, 'wrong-password');
	await expect(page.getByText('Huckleberry sign-in failed. Check the email and password.')).toBeVisible({ timeout: 30_000 });
	await snap(page, 'h1-wrong-password', true);

	await page.reload();
	await runImport(page, 'any-password');
	await expect(page.getByLabel('Huckleberry password')).toHaveValue('');
	await snap(page, 'h2-importing', true);
	await expect(page.getByRole('heading', { name: 'Import complete' })).toBeVisible({ timeout: 60_000 });
	await expect(page.getByText(/^2 children · 60 entries/)).toBeVisible();
	await snap(page, 'h3-done', true);
	const first = await entryCount(api);
	expect(first).toEqual({ names: ['Ada', 'Leo', 'Mia'], n: 60 });

	// the imported children are in the switcher, with their history
	await page.getByRole('button', { name: /^Child: Ada/ }).click();
	await expect(page.getByRole('button', { name: /Mia/ })).toBeVisible();
	await snap(page, 'h4-switcher');
	await page.getByRole('button', { name: /Leo/ }).click();
	await page.getByRole('link', { name: 'Home' }).click();
	await expect(page.getByRole('button', { name: /^Child: Leo/ })).toBeVisible();
	await expect(page.getByText(/ ago$/).first()).toBeVisible();
	await snap(page, 'h5-leo-home');

	// again: no duplicates
	await page.goto('/settings/import');
	await runImport(page, 'any-password');
	await expect(page.getByRole('heading', { name: 'Import complete' })).toBeVisible({ timeout: 60_000 });
	await snap(page, 'h6-again', true);
	expect(await entryCount(api)).toEqual(first);
});
