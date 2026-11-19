// Each test acts as its own new parent (a fresh dev user), so tests do not share families.
import { test as base, expect, request as pwRequest, type APIRequestContext, type Page } from '@playwright/test';

export const TZ = 'Australia/Brisbane';
const SHOTS = new URL('../recordings/m2/screens/', import.meta.url).pathname;

/** "YYYY-MM-DDTHH:MM" in the family time zone (the API reads offset-less times in that zone). */
export function local(d: Date | number = Date.now()): string {
	const p = Object.fromEntries(
		new Intl.DateTimeFormat('en-AU', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
			.formatToParts(new Date(d))
			.map((x) => [x.type, x.value])
	);
	return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** What the parent sees on the phone screen. Pass `bottom` to scroll to the end first. */
export async function shot(page: Page, name: string, bottom = false) {
	if (bottom) await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
	await page.waitForTimeout(300); // let the sheet animation finish
	await page.screenshot({ path: `${SHOTS}${name}.png` });
}

type Fixtures = {
	email: string;
	api: APIRequestContext;
	/** Make a family with one child through the API. */
	family: { childId: number; name: string };
};

export const test = base.extend<Fixtures>({
	email: async ({}, use, info) => {
		await use(`parent-${info.workerIndex}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}@example.com`);
	},
	api: async ({ email, baseURL }, use) => {
		const ctx = await pwRequest.newContext({ baseURL: `${baseURL}/api/v1/`, extraHTTPHeaders: { 'X-Dev-User': email } });
		await use(ctx);
		await ctx.dispose();
	},
	family: async ({ api }, use) => {
		expect((await api.post('families', { data: { name: 'Test family', timezone: TZ } })).ok()).toBeTruthy();
		const born = new Date(Date.now() - 150 * 86400_000).toISOString().slice(0, 10);
		const res = await api.post('children', { data: { name: 'Mia', birthdate: born, sex: 'F' } });
		expect(res.ok()).toBeTruthy();
		await use({ childId: (await res.json()).id, name: 'Mia' });
	},
	page: async ({ page, email }, use) => {
		await page.addInitScript((e) => localStorage.setItem('fb.devUser', e), email);
		await use(page);
	}
});

export { expect, pwRequest as request };

/** Open a tracker tile on Home. */
export async function openTile(page: Page, label: string) {
	await page.getByRole('button', { name: new RegExp(`^${label}\\b`) }).first().click();
	return page.getByRole('dialog');
}
