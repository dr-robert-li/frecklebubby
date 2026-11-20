// M17 invite only server. Project `m17`: its own server with OPERATOR_EMAILS=operator@example.com.
import type { Browser, Page } from '@playwright/test';
import { expect, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm17');
const run = Date.now();
const INVITED = `invited-${run}@example.com`;
const WAITING = `waiting-${run}@example.com`;
const STRANGER = `stranger-${run}@example.com`;
const REFUSED = 'This server is invite only. Ask the person who runs it for an invite.';

async function as(browser: Browser, email: string): Promise<Page> {
	const ctx = await browser.newContext({ ...test.info().project.use, recordVideo: { dir: test.info().outputPath(email.split('@')[0]) } });
	await ctx.addInitScript((e) => localStorage.setItem('fb.devUser', e), email);
	return ctx.newPage();
}

async function invite(page: Page, email: string) {
	await page.getByLabel('Invite an email').fill(email);
	await page.getByRole('button', { name: 'Invite', exact: true }).click();
	await expect(page.getByRole('list', { name: 'Invites' }).getByText(email)).toBeVisible();
}

test('the operator invites people; only invited people get in', async ({ browser }) => {
	const op = await as(browser, 'operator@example.com');
	await op.goto('/onboarding');
	await op.getByLabel('Family name').fill('Operator family');
	await op.getByRole('button', { name: 'Next' }).click();
	await expect(op.getByRole('heading', { name: 'Add your child' })).toBeVisible();
	await op.getByLabel('Name').fill('Ivy');
	await op.getByLabel('Date of birth').fill('2026-07-01');
	await op.getByRole('button', { name: 'Girl' }).click();
	await op.getByRole('button', { name: 'Start tracking' }).click();
	await expect(op).toHaveURL(/\/$/);

	await op.goto('/settings');
	await op.getByRole('link', { name: /Server access/ }).click();
	await invite(op, INVITED);
	await expect(op.getByText('Waiting since')).toBeVisible();
	await snap(op, '1-operator-invited');

	// The invited email signs in and starts a family.
	const invited = await as(browser, INVITED);
	await invited.goto('/');
	await expect(invited).toHaveURL(/\/onboarding/);
	await invited.getByLabel('Family name').fill('Invited family');
	await invited.getByRole('button', { name: 'Next' }).click();
	await expect(invited.getByRole('heading', { name: 'Add your child' })).toBeVisible();
	await invited.getByLabel('Name').fill('Ada');
	await invited.getByLabel('Date of birth').fill('2026-08-01');
	await invited.getByRole('button', { name: 'Girl' }).click();
	await invited.getByRole('button', { name: 'Start tracking' }).click();
	await expect(invited.getByRole('button', { name: /Child: Ada/ })).toBeVisible();
	await snap(invited, '2-invited-home');
	await invited.goto('/settings');
	await expect(invited.getByRole('link', { name: /Server access/ })).toHaveCount(0);

	// An email with no invite is refused with a plain page.
	const stranger = await as(browser, STRANGER);
	await stranger.goto('/');
	await expect(stranger.getByRole('heading', { name: 'No access' })).toBeVisible();
	await expect(stranger.getByText(REFUSED)).toBeVisible();
	await snap(stranger, '3-refused');

	// The operator sees the family (no child data) and the used invite.
	await op.reload();
	const families = op.getByRole('list', { name: 'Families' });
	await expect(families.getByText('Invited family')).toBeVisible();
	await expect(families.getByText(INVITED)).toBeVisible();
	await expect(op.getByText('Ada')).toHaveCount(0);
	await expect(op.getByRole('list', { name: 'Invites' }).getByText(/^Used /)).toBeVisible();

	// A waiting invite can be removed: that email is then refused.
	await invite(op, WAITING);
	await op.getByRole('button', { name: `Remove invite for ${WAITING}` }).click();
	await expect(op.getByText('Invite removed')).toBeVisible();
	await expect(op.getByRole('list', { name: 'Invites' }).getByText(WAITING)).toHaveCount(0);
	const waiting = await as(browser, WAITING);
	await waiting.goto('/');
	await expect(waiting.getByText(REFUSED)).toBeVisible();

	// A used invite cannot be removed: the family belongs to its owner.
	await op.getByRole('button', { name: `Remove invite for ${INVITED}` }).click();
	await expect(op.getByRole('alert')).toHaveText('This invite is used. The family is now managed by its owner.');
	await snap(op, '4-used-invite-stays', true);
	await invited.reload();
	await expect(invited.getByRole('heading', { name: 'Settings' })).toBeVisible();

	for (const p of [op, invited, stranger, waiting]) await p.context().close();
});
