// The day and night plan: the app calculates one typical 24 hours from the child's own logs. No AI model is necessary.
import { expect, local, setAge, shot, test } from './fixtures';

test('the plan shows typical times first, then the child\'s own day and night with the night feeds', async ({ page, api, family }) => {
	await setAge(api, family.childId, 150); // about 5 months
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const plan = page.getByRole('region', { name: 'Day and night plan' });
	await expect(plan).toContainText('From typical times for the age.');
	await expect(plan.locator('.schedule li.wake')).toContainText('typical for the age');
	await expect(plan).toContainText('No complete day of sleep is logged');
	await shot(page, '12-plan-typical');

	// 8 days: night 19:30 to 06:10 with feeds at 23:00 and 03:10, naps at 08:30, 12:00 and 15:30.
	const day = (n: number) => local(Date.now() - n * 86400_000).slice(0, 10);
	const post = async (data: object) => expect((await api.post(`children/${family.childId}/entries`, { data })).ok(), JSON.stringify(data)).toBeTruthy();
	for (let n = 9; n >= 1; n--) {
		await post({ type: 'sleep', started_at: `${day(n)}T19:30`, ended_at: `${day(n - 1)}T06:10`, data: {} });
		await post({ type: 'nursing', started_at: `${day(n)}T23:00`, ended_at: `${day(n)}T23:15`, data: {} });
		await post({ type: 'nursing', started_at: `${day(n - 1)}T03:10`, ended_at: `${day(n - 1)}T03:25`, data: {} });
		if (n > 1)
			for (const [a, b] of [['08:30', '09:30'], ['12:00', '13:15'], ['15:30', '16:00']])
				await post({ type: 'sleep', started_at: `${day(n - 1)}T${a}`, ended_at: `${day(n - 1)}T${b}`, data: {} });
	}
	await page.reload();
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	await expect(plan).toContainText("own logs of the last 14 days");
	const rows = plan.locator('.schedule li');
	await expect(rows).toHaveText([/06:10\s*Wake up/, /08:30\s*Nap 1 to 09:30/, /12:00\s*Nap 2 to 13:15/, /15:30\s*Nap 3 to 16:00/, /19:30\s*Bedtime/, /23:00\s*Night feed/, /03:10\s*Night feed/]);
	await expect(plan.getByRole('heading', { name: 'Night', exact: true })).toBeVisible();
	await expect(plan.locator('.facts')).toContainText('Feeds at night');
	await expect(plan.locator('.facts')).toContainText('Common for the age');
	await shot(page, '12-plan-own');
	// A source of a note opens.
	await plan.getByRole('button', { name: /^Source \d+$/ }).first().click();
	await expect(page.getByRole('dialog')).toBeVisible();
	await shot(page, '12-plan-source', true);
});
