import { expect, shot, test } from './fixtures';

test('a new parent makes a family and adds a child', async ({ page }) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/onboarding/);
	await expect(page.getByRole('heading', { name: 'Make your family' })).toBeVisible();
	await shot(page, '01-onboarding-family');

	await page.getByLabel('Family name').fill('The Lee family');
	await expect(page.getByLabel('Time zone')).toHaveValue('Australia/Brisbane');
	await page.getByRole('button', { name: 'Next' }).click();

	await expect(page.getByRole('heading', { name: 'Add your child' })).toBeVisible();
	await page.getByLabel('Name').fill('Freya');
	await page.getByLabel('Date of birth').fill('2026-07-01');
	await page.getByRole('button', { name: 'Girl' }).click();
	await shot(page, '01-onboarding-child');
	await page.getByRole('button', { name: 'Start tracking' }).click();

	await expect(page).toHaveURL(/\/$/);
	await expect(page.getByRole('button', { name: /Child: Freya/ })).toBeVisible();
	await expect(page.getByRole('button', { name: /^Sleep/ })).toBeVisible();
	await expect(page.getByText('Nothing logged today')).toBeVisible();
	await shot(page, '01-home-empty');
});
