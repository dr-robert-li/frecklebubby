// M15/M16 journeys. Project `m15`: its own server with the real model and a wait list of one request.
import type { Page } from '@playwright/test';
import { expect, local, request, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm15');
const QUESTION = 'How many wet nappies a day is normal?';

test('a: the owner deletes the family after typing its name', async ({ page, api, family }) => {
	expect((await api.post(`children/${family.childId}/entries`, { data: { type: 'bottle', started_at: local(), data: { amount_ml: 120 } } })).ok()).toBeTruthy();
	await page.goto('/settings');
	await page.getByRole('link', { name: /Delete data/ }).click();
	const form = page.getByRole('form', { name: 'Delete the family' });
	await expect(form.getByText('Type the family name to confirm: Test family')).toBeVisible();
	const button = form.getByRole('button', { name: 'Delete the family for good' });
	await form.getByLabel(/Type the family name/).fill('Test famil');
	await expect(button).toBeDisabled();
	await expect(page.getByText('That account is separate from your data here')).toBeVisible();
	await snap(page, 'a1-delete-family-confirm');
	await form.getByLabel(/Type the family name/).fill('Test family');
	await expect(button).toBeEnabled();
	await snap(page, 'a2-delete-family-ready');
	await button.click();
	await expect(page).toHaveURL(/\/onboarding/);
	await expect(page.getByRole('heading', { name: 'Make your family' })).toBeVisible();
	await snap(page, 'a3-after-delete');
	expect((await api.get(`children/${family.childId}`)).status()).toBe(404); // the child is gone
	expect((await (await api.get('me')).json()).family).toBeNull();
});

test('b: the assistant shows that it waits, and that it is busy', async ({ page, api, family, browser, baseURL }) => {
	// A sleep plan holds the model; the chat waits behind it. The wait list holds one request.
	expect((await api.post(`children/${family.childId}/sleep/plan`)).status()).toBe(202);
	expect((await (await api.get(`children/${family.childId}/sleep/plan/job`)).json()).status).toBe('running');
	await page.goto('/assistant');
	await page.getByLabel('Your question').fill(QUESTION);
	await page.getByRole('button', { name: 'Send' }).click();
	const answer = page.locator('.msgs li.assistant').last();
	await expect(answer.getByText('Waiting for the assistant…')).toBeVisible({ timeout: 15_000 });
	await snap(page, 'b1-waiting');

	// A second parent asks now: the wait list is full.
	const other = `busy-${Date.now()}@example.com`;
	const otherApi = await request.newContext({ baseURL: `${baseURL}/api/v1/`, extraHTTPHeaders: { 'X-Dev-User': other } });
	expect((await otherApi.post('families', { data: { name: 'Other family', timezone: 'Australia/Brisbane' } })).ok()).toBeTruthy();
	expect((await otherApi.post('children', { data: { name: 'Leo', birthdate: local(Date.now() - 100 * 86400_000).slice(0, 10) } })).ok()).toBeTruthy();
	const ctx = await browser.newContext({ ...test.info().project.use, recordVideo: { dir: test.info().outputPath('busy') } });
	await ctx.addInitScript((e) => localStorage.setItem('fb.devUser', e), other);
	const page2 = await ctx.newPage();
	await page2.goto(`${baseURL}/assistant`);
	await page2.getByLabel('Your question').fill(QUESTION);
	await page2.getByRole('button', { name: 'Send' }).click();
	await expect(page2.getByText('The assistant is busy. Try again in a minute.')).toBeVisible();
	await snap(page2, 'b2-busy');
	await ctx.close();
	await otherApi.dispose();

	// The first parent gets the answer when the model is free.
	await expect(answer).toContainText('General information, not medical advice.', { timeout: 300_000 });
	await expect(answer.getByText('Waiting for the assistant…')).toBeHidden();
	await snap(page, 'b3-answer-after-wait');
});
