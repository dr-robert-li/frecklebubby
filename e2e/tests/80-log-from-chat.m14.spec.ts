// M14: the parent logs in plain words in the assistant chat. Project `m14`: the real model on the second server.
import type { Locator, Page } from '@playwright/test';
import { expect, local, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm14');
const timeline = (page: Page) => page.getByRole('list', { name: 'Timeline' });
/** "HH:MM" now and the minute before (the model call takes a few seconds), as a RegExp group. */
const nowish = () => [0, 1].map((d) => local(Date.now() - d * 60_000).slice(11)).join('|');

/** Send a chat message and wait until the turn is complete (the input is free again). */
async function send(page: Page, text: string): Promise<Locator> {
	await page.getByLabel('Your question').fill(text);
	await page.getByRole('button', { name: 'Send' }).click();
	const turn = page.locator('.msgs li.assistant').last();
	await expect(page.locator('.msgs')).toHaveAttribute('aria-busy', 'true');
	await expect(page.locator('.msgs')).toHaveAttribute('aria-busy', 'false', { timeout: 120_000 });
	return turn;
}

test('a: a report is logged in the chat, shows on Home, survives a reload and can be undone', async ({ page, family }) => {
	await page.goto('/assistant');
	const at = nowish();
	const turn = await send(page, 'she had 120 ml of formula just now');
	const block = turn.getByRole('group', { name: 'Logged' });
	const row = new RegExp(`^Bottle – 120 ml formula – (${at})$`);
	await expect(block.getByText(row)).toBeVisible();
	await expect(block.getByRole('button', { name: new RegExp(`^Undo Bottle – 120 ml formula – (${at})$`) })).toBeVisible();
	await expect(turn.getByText('General information, not medical advice.')).toHaveCount(0); // a report gets no answer
	await snap(page, 'a1-logged');

	await page.goto('/');
	await expect(timeline(page).getByRole('button', { name: new RegExp(`^Edit Bottle at (${at})$`) })).toContainText('120 ml');
	await snap(page, 'a2-home-timeline', true);

	await page.goto('/assistant');
	const again = page.locator('.msgs li.assistant').last().getByRole('group', { name: 'Logged' });
	await expect(again.getByText(row)).toBeVisible(); // the saved chat keeps the block
	await again.getByRole('button', { name: new RegExp(`^Undo Bottle – 120 ml formula – (${at})$`) }).click();
	await expect(again.getByText('Undone', { exact: true })).toBeVisible();
	await expect(again.getByRole('button', { name: /^Undo / })).toHaveCount(0);
	await snap(page, 'a3-undone');
	await page.reload();
	await expect(page.locator('.msgs li.assistant').last().getByText('Undone', { exact: true })).toBeVisible();

	await page.goto('/');
	await expect(timeline(page).getByRole('button', { name: /^Edit Bottle at / })).toHaveCount(0);
});

test('b: log and ask in one turn, edit the saved sleep, and a guess that is not saved', async ({ page, family }) => {
	await page.goto('/assistant');
	const turn = await send(page, 'she only slept 20 minutes, is that normal?');
	const block = turn.getByRole('group', { name: 'Logged' });
	await expect(block.getByText(/^Sleep – \d\d:\d\d to \d\d:\d\d \(20 min\)$/)).toBeVisible();
	await expect(turn).toContainText('General information, not medical advice.'); // the question is answered too
	await snap(page, 'b1-log-and-ask');

	await block.getByRole('button', { name: /^Edit Sleep – / }).click();
	const sheet = page.getByRole('dialog');
	await expect(sheet).toBeVisible();
	await snap(page, 'b2-edit-sheet');
	await sheet.getByRole('button', { name: 'Close' }).click();
	await expect(sheet).toBeHidden();

	// No amount: the parser does not guess one, so nothing is saved until the parent checks it.
	const guess = await send(page, 'she had a bottle');
	await expect(guess.getByRole('group', { name: 'Logged' })).toHaveCount(0);
	await expect(guess.getByText(/^Check this before I save/)).toBeVisible();
	await expect(guess.getByText(/^Not sure: /)).toBeVisible();
	await snap(page, 'b3-not-sure');
	await guess.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(guess.getByText(/^Check this before I save/)).toHaveCount(0);

	// A plain question is never logged.
	const q = await send(page, 'how much milk does a baby this age need?');
	await expect(q).toContainText('General information, not medical advice.');
	await expect(q.getByRole('group', { name: 'Logged' })).toHaveCount(0);

	await page.goto('/');
	await expect(timeline(page).getByRole('button', { name: /^Edit Sleep at / })).toHaveCount(1);
	await expect(timeline(page).getByRole('button', { name: /^Edit Bottle at / })).toHaveCount(0);
});

test('c: start a nap from the chat, see the timer on Home, undo cancels it', async ({ page, family }) => {
	await page.goto('/assistant');
	const turn = await send(page, 'start a nap');
	const block = turn.getByRole('group', { name: 'Logged' });
	await expect(block.getByText(/^Sleep timer – start – \d\d:\d\d$/)).toBeVisible();
	await expect(block.getByRole('button', { name: /^Edit / })).toHaveCount(0); // a timer has no entry yet
	await snap(page, 'c1-timer-logged');
	await page.goto('/');
	await expect(page.getByRole('region', { name: 'Sleep timer' })).toBeVisible();
	await page.goto('/assistant');
	await page.locator('.msgs li.assistant').last().getByRole('button', { name: /^Undo Sleep timer – start – / }).click();
	await expect(page.locator('.msgs li.assistant').last().getByText('Undone', { exact: true })).toBeVisible();
	await page.goto('/');
	await expect(page.getByRole('region', { name: 'Sleep timer' })).toHaveCount(0);
});
