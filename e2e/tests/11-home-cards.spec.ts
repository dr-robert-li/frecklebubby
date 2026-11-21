// The parent changes the size and the place of the Home cards (hold a card), for this device.
import type { Page } from '@playwright/test';
import { expect, shot, test } from './fixtures';

const cards = (page: Page) => page.locator('[data-card]');
const order = (page: Page) => cards(page).evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.card));
const bar = (page: Page) => page.getByRole('toolbar', { name: 'Change the cards' });

async function hold(page: Page, type: string) {
	const box = (await page.locator(`[data-card="${type}"]`).boundingBox())!;
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	await page.mouse.down();
	await page.waitForTimeout(700);
}

test('hold a card: change the size, move it, and the layout stays', async ({ page, family }) => {
	await page.goto('/');
	const solids = page.locator('[data-card="solids"]');
	await expect(solids).toHaveText('Solids'); // small: the name only
	expect((await order(page)).slice(0, 6)).toEqual(['sleep', 'nursing', 'bottle', 'nappy', 'activity', 'cry']);
	await expect(page.locator('[data-card="activity"]')).toContainText('Not yet'); // a wide card shows the time too

	await hold(page, 'solids');
	await page.mouse.up();
	await expect(bar(page)).toContainText('Solids');
	await expect(page.getByRole('dialog')).toHaveCount(0); // a hold does not open the form
	await bar(page).getByRole('button', { name: 'Wide' }).click();
	await expect(solids).toContainText('Foods and how the child liked them');
	await expect(solids).toContainText('Not yet');
	await bar(page).getByRole('button', { name: 'Large' }).click();
	await expect(solids).toHaveText(/Solids\s*Not yet/);
	await shot(page, 'cards-1-edit', false, 'm19');

	// Tap another card in this mode: it is selected, the form stays closed. Then move it with the buttons.
	await page.locator('[data-card="note"]').click();
	await expect(bar(page)).toContainText('Note');
	const before = await order(page);
	await bar(page).getByRole('button', { name: 'Move earlier' }).click();
	const after = await order(page);
	expect(after.indexOf('note')).toBe(before.indexOf('note') - 1);

	// Drag: Note goes up to the place of a card before it.
	await page.locator('[data-card="note"]').evaluate((e) => e.scrollIntoView({ block: 'center' }));
	const was = (await order(page)).indexOf('note');
	const target = (await page.locator(`[data-card="${(await order(page))[was - 3]}"]`).boundingBox())!;
	const note = (await page.locator('[data-card="note"]').boundingBox())!;
	await page.mouse.move(note.x + 20, note.y + 20);
	await page.mouse.down();
	await page.mouse.move(target.x + 30, target.y + 30, { steps: 8 });
	await page.mouse.up();
	const place = (await order(page)).indexOf('note');
	expect(place).toBeLessThan(was);
	await shot(page, 'cards-2-moved', false, 'm19');

	// A press outside the cards ends the mode.
	await page.getByRole('heading', { name: 'Today' }).click();
	await expect(bar(page)).toHaveCount(0);
	await page.reload();
	await expect(cards(page).first()).toBeVisible();
	expect((await order(page))[place]).toBe('note');
	await expect(page.locator('[data-card="solids"]')).toHaveText(/Solids\s*Not yet/);
	// A tap opens the form again.
	await page.locator('[data-card="solids"]').click();
	await expect(page.getByRole('dialog')).toBeVisible();
});

test('reset gives the first layout back', async ({ page, family }) => {
	await page.goto('/');
	await hold(page, 'sleep');
	await page.mouse.up();
	await bar(page).getByRole('button', { name: 'Small' }).click();
	await bar(page).getByRole('button', { name: 'Move later' }).click();
	expect((await order(page))[0]).toBe('nursing');
	await bar(page).getByRole('button', { name: 'Reset' }).click();
	expect((await order(page))[0]).toBe('sleep');
	await bar(page).getByRole('button', { name: 'Done' }).click();
	await expect(bar(page)).toHaveCount(0);
	await expect(page.locator('[data-card="sleep"]')).toHaveText(/Sleep\s*Not yet/);
});
