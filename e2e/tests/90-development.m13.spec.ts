// M13: development guidance. Project `m13`: the real model on the second server.
import type { Locator, Page } from '@playwright/test';
import { expect, local, setAge, shot, test } from './fixtures';

const snap = (page: Page, name: string, bottom = false) => shot(page, name, bottom, 'm13');
const FOOTER = 'General information, not medical advice.';

async function ask(page: Page, question: string): Promise<Locator> {
	await page.getByLabel('Your question').fill(question);
	await page.getByRole('button', { name: 'Send' }).click();
	const answer = page.locator('.msgs li.assistant').last();
	await expect(answer).toContainText(FOOTER, { timeout: 120_000 });
	return answer;
}

test('a: a question about a milestone gets a cited answer with tips; insights show development around now', async ({ page, api, family }) => {
	await setAge(api, family.childId, 150);
	await page.goto('/assistant');
	const answer = await ask(page, 'how can I help her learn to sit?');
	// Cited: the source chips include the CDC tips or the WHO windows (picked by her age, not by search).
	const chips = answer.locator('.cite');
	await expect(chips.first()).toBeVisible();
	expect((await chips.allInnerTexts()).join(' | ')).toMatch(/CDC|WHO/);
	await expect(answer.getByRole('group', { name: 'Logged' })).toHaveCount(0); // a question is not logged
	await snap(page, 'a1-sit-answer');

	const gap = await ask(page, 'when is the 4 month sleep regression?');
	await expect(gap.locator('p').first()).toHaveText('I have no source on sleep regressions.');
	await snap(page, 'a2-no-source');

	await page.getByRole('tab', { name: 'Insights' }).click();
	const move = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Moving and playing around now', exact: true }) });
	await expect(move).toContainText('sit without support');
	await expect(move).toContainText('WHO: Most healthy babies');
	await expect(move).not.toContainText('should');
	await move.scrollIntoViewIfNeeded();
	await snap(page, 'a3-development-card');
	const ms = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Milestones by 4 months', exact: true }) });
	await expect(ms).toContainText('CDC tips for this age: ');
	await ms.scrollIntoViewIfNeeded();
	await snap(page, 'a4-milestone-tips');
});

test('b: born early: the due date in the child form moves the milestone bands to the corrected age', async ({ page, family }) => {
	await page.goto('/settings/children');
	await page.getByRole('button', { name: 'Change Mia' }).click();
	const sheet = page.getByRole('dialog');
	await expect(sheet.getByText(/use the corrected age \(from the due date\) until 2 years/)).toBeVisible();
	// Mia is 150 days old; due 8 weeks after the birth = corrected age about 3 months.
	const due = local(Date.now() - (150 - 56) * 86400_000).slice(0, 10);
	await sheet.getByLabel('Born early? Due date').fill(due);
	await snap(page, 'b1-due-date');
	await sheet.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByText('Child saved')).toBeVisible();

	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Milestones' }).click();
	await expect(page.getByText(/The bands use the corrected age \(3\.\d months from the due date\)/)).toBeVisible();
	await page.getByRole('tab', { name: 'Insights' }).click();
	await expect(page.getByRole('heading', { name: 'Milestones by 2 months', exact: true })).toBeVisible();
	await expect(page.getByText(/Ages here are counted from the due date \(corrected age\)/).first()).toBeVisible();
	await snap(page, 'b2-corrected-insights');
});

test('c: reaching a new age band sends one message to the bell; the switch is in reminder settings', async ({ page, api, family }) => {
	// 4 months starts at day 122; Mia is 125 days old. Daytime for her: the night starts 6 hours from now.
	await setAge(api, family.childId, 125);
	const hm = (h: number) => local(Date.now() + h * 3600_000).slice(11);
	expect((await api.patch(`children/${family.childId}`, { data: { night_start: hm(6), morning_cutoff: hm(-6) } })).ok()).toBeTruthy();
	await page.goto('/settings/reminders');
	await expect(page.getByRole('checkbox', { name: 'Milestone age band messages on' })).toBeChecked();
	await snap(page, 'c1-reminder-switch');

	await page.goto('/');
	// The server checks each 60 s; the app reads the unread count every 15 s.
	const bell = page.getByRole('link', { name: 'Notifications, 1 unread' });
	await expect(bell).toBeVisible({ timeout: 150_000 });
	await bell.click();
	await expect(page.getByText('Mia: milestones by 4 months', { exact: true })).toBeVisible();
	await expect(page.getByText(/^Mia is now in the 4-month band of the CDC milestones checklist\. Things to look for: /)).toBeVisible();
	await snap(page, 'c2-band-notification');
});
