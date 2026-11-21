// The day and night plan: the app calculates one typical 24 hours as a timeline of sleep blocks and feeds.
// The start point is the child's own logs; then one small step toward best practice. No AI model is necessary.
import type { APIRequestContext } from '@playwright/test';
import { expect, local, setAge, shot, test } from './fixtures';

const day = (n: number) => local(Date.now() - n * 86400_000).slice(0, 10);
/** `days` days of logs. A sleep that ends before it starts ends on the next day. */
async function seed(api: APIRequestContext, childId: number, days: number, sleeps: [string, string][], feeds: string[]) {
	const post = async (data: object) => expect((await api.post(`children/${childId}/entries`, { data })).ok(), JSON.stringify(data)).toBeTruthy();
	for (let n = days + 1; n >= 2; n--) {
		for (const [a, b] of sleeps) await post({ type: 'sleep', started_at: `${day(n)}T${a}`, ended_at: `${day(b < a ? n - 1 : n)}T${b}`, data: {} });
		for (const f of feeds) await post({ type: 'nursing', started_at: `${day(n)}T${f}`, ended_at: `${day(n)}T${f.slice(0, 4)}9`, data: {} });
	}
}

test('5 months: typical times first, then the child\'s own sleep blocks with the feeds of the day and the night', async ({ page, api, family }) => {
	await setAge(api, family.childId, 150);
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const plan = page.getByRole('region', { name: 'Day and night plan' });
	await expect(plan).toContainText('From typical times for the age.');
	await expect(plan.locator('.schedule li.night')).toContainText('typical for the age');
	await expect(plan).toContainText('No complete day of sleep is logged');
	await shot(page, '12-plan-typical');

	// 13.4 hours of sleep: inside the recommended 12 to 16 hours, so the plan is the child's own pattern.
	await seed(api, family.childId, 9, [['19:30', '06:10'], ['08:30', '09:30'], ['12:00', '13:15'], ['15:30', '16:00']], ['06:20', '09:40', '13:20', '16:10', '19:00', '23:00', '03:10']);
	await page.reload();
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	await expect(plan).toContainText('own logs of the last 14 days');
	await expect(plan.locator('.schedule li')).toHaveText([
		/06:20\s*Feed/, /08:30\s*Nap 1 to 09:30/, /09:40\s*Feed/, /12:00\s*Nap 2 to 13:15/, /13:20\s*Feed/, /15:30\s*Nap 3 to 16:00/, /16:10\s*Feed/,
		/19:00\s*Feed/, /19:30\s*Night sleep to 06:10/, /23:00\s*Feed/, /03:10\s*Feed/
	]);
	await expect(plan.getByRole('note', { name: 'Small steps in this plan' })).toHaveCount(0);
	await expect(plan.locator('.facts')).toContainText('Feeds at night');
	await shot(page, '12-plan-own');
	await page.screenshot({ path: `recordings/m2/screens/12-plan-own-full.png`, fullPage: true });
	await plan.getByRole('button', { name: /^Source \d+$/ }).first().click();
	await expect(page.getByRole('dialog')).toBeVisible();
});

test('10 months with too little sleep: one small step, and the reason', async ({ page, api, family }) => {
	await setAge(api, family.childId, 310);
	await seed(api, family.childId, 9, [['21:00', '06:00'], ['10:00', '10:45'], ['14:30', '15:15']], ['06:15', '11:00', '15:30', '20:30', '02:00']);
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const plan = page.getByRole('region', { name: 'Day and night plan' });
	const steps = plan.getByRole('note', { name: 'Small steps in this plan' });
	await expect(steps).toContainText('about 10.5 hours of sleep in 24 hours');
	await expect(steps).toContainText('12 to 16 hours');
	await expect(steps).toContainText('adds about 20 minutes');
	const night = plan.locator('.schedule li.night');
	await expect(night).toContainText('20:40');
	await expect(night).toContainText("20 minutes earlier than Mia's usual 21:00");
	await expect(plan.locator('.schedule li.changed')).toHaveCount(1); // one step, not the full 90 minutes
	await shot(page, '12-plan-step');
	await page.screenshot({ path: `recordings/m2/screens/12-plan-step-full.png`, fullPage: true });
});

test('a young baby: sleep blocks from the usual hours, one new sleep and one new feed', async ({ page, api, family }) => {
	await setAge(api, family.childId, 40);
	await seed(api, family.childId, 8, [['01:30', '03:30'], ['04:00', '06:10'], ['09:00', '10:00'], ['17:00', '18:30'], ['20:00', '22:00']], ['00:30', '03:40', '06:30', '10:30', '14:00', '18:40', '22:10']);
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const plan = page.getByRole('region', { name: 'Day and night plan' });
	const steps = plan.getByRole('note', { name: 'Small steps in this plan' });
	await expect(steps).toContainText('14 to 17 hours');
	await expect(steps).toContainText('adds 1 feed');
	await expect(plan.locator('.schedule li.nap, .schedule li.night')).toHaveCount(6); // 5 usual blocks and 1 new
	await expect(plan.locator('.schedule li.changed')).toHaveCount(2);
	await expect(plan.locator('.schedule li.changed').first()).toContainText('Offer a sleep');
	await expect(plan.locator('.schedule li.feed')).toHaveCount(8);
	await expect(plan).toContainText('no fixed day and night yet');
	await shot(page, '12-plan-young');
	await page.screenshot({ path: `recordings/m2/screens/12-plan-young-full.png`, fullPage: true });
	await shot(page, '12-plan-young-bottom', true);
});
