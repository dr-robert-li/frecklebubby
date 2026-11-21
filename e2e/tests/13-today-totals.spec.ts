// The totals under "Today": two rows, and no text outside a card.
import { expect, local, shot, test } from './fixtures';

test('the totals of today are in two rows and the times stay inside the cards', async ({ page, api, family }) => {
	// Times in the last hour, so that the test works at each time of the day (also just after midnight).
	const ago = (minutes: number) => local(Date.now() - minutes * 60_000);
	for (const data of [
		{ type: 'sleep', started_at: ago(55), ended_at: ago(10), data: {} },
		{ type: 'nursing', started_at: ago(8), ended_at: ago(1), data: { left_seconds: 200, right_seconds: 220 } }
	])
		expect((await api.post(`children/${family.childId}/entries`, { data })).ok(), JSON.stringify(data)).toBeTruthy();
	await page.goto('/');
	const cards = page.locator('.totals > div');
	await expect(cards).toHaveCount(5);
	const boxes = await cards.evaluateAll((els) => els.map((e) => ({ top: e.getBoundingClientRect().top, over: e.scrollWidth > e.clientWidth + 1 })));
	expect(boxes[0].top).toBe(boxes[1].top); // Sleep and Breastfed
	expect(boxes[2].top).toBeGreaterThan(boxes[0].top); // Wee, Poo, Bottle below
	expect(new Set(boxes.slice(2).map((b) => b.top)).size).toBe(1);
	expect(boxes.some((b) => b.over)).toBe(false);
	await page.getByRole('heading', { name: 'Today' }).scrollIntoViewIfNeeded();
	await shot(page, '13-today-totals');
});
