// A wide button must not touch the element above it.
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

/** The space above each visible wide button: [button text, pixels to the element before it]. */
const gaps = (page: Page) =>
	page.locator('button.wide:visible').evaluateAll((els) =>
		els.flatMap((b) => {
			let prev = b.previousElementSibling;
			while (prev && (prev as HTMLElement).offsetParent === null) prev = prev.previousElementSibling; // hidden or fixed
			if (!prev) return [];
			const gap = b.getBoundingClientRect().top - prev.getBoundingClientRect().bottom;
			return [[(b.textContent ?? '').trim(), Math.round(gap)] as [string, number]];
		})
	);

test('wide buttons have space above them on all pages', async ({ page, family }) => {
	const found: string[] = [];
	for (const [url, tab] of [['/assistant', 'Sleep plan'], ['/reports', ''], ['/settings/ai', ''], ['/settings/import', ''], ['/settings/reminders', ''], ['/settings/notifications', ''], ['/settings/children', '']]) {
		await page.goto(url);
		if (tab) await page.getByRole('tab', { name: tab }).click();
		await page.waitForLoadState('networkidle');
		for (const add of await page.getByRole('button', { name: /^(Add|New) / }).all()) await add.click().catch(() => {}); // open the forms
		for (const [text, gap] of await gaps(page)) {
			found.push(`${url}: ${text}`);
			expect(gap, `${url}: "${text}" has ${gap}px above it`).toBeGreaterThanOrEqual(8);
		}
	}
	expect(found.length).toBeGreaterThanOrEqual(4);
});
