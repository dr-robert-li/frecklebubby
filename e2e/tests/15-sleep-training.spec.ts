// Sleep training: an option, off by default. Age limits, set-up, the steps for tonight, the scale and a night report.
import { expect, local, setAge, shot, test } from './fixtures';

test('a baby of 3 months cannot start; a baby of 5 months gets a warning to confirm', async ({ page, api, family }) => {
	await setAge(api, family.childId, 90);
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const card = page.getByRole('region', { name: 'Sleep training' });
	await expect(card).toContainText('not for a baby younger than 4 months');
	await expect(card.getByRole('button', { name: 'Set up sleep training' })).toHaveCount(0);

	await setAge(api, family.childId, 155);
	await page.reload();
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	await card.getByRole('button', { name: 'Set up sleep training' }).click();
	await expect(card).toContainText('start at about 6 months');
	await expect(card.getByRole('radio', { name: /extinction/i })).toHaveCount(1); // graduated extinction only
	await expect(card.getByRole('radio', { name: /Bedtime fading/ })).toHaveCount(0);
	await shot(page, '15-training-warning');
});

test('9 months: set up graduated extinction, see the steps, report a hard night, the scale moves', async ({ page, api, family }) => {
	await setAge(api, family.childId, 280);
	await page.goto('/assistant');
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	const card = page.getByRole('region', { name: 'Sleep training' });
	await expect(card).toContainText('It is off now');
	await card.getByRole('button', { name: 'Set up sleep training' }).click();
	await expect(card.getByRole('radio')).toHaveCount(4); // 2 methods (no fading before 12 months) and the scale switch
	await card.getByRole('radio', { name: /Graduated extinction/ }).check();
	await expect(card.getByRole('slider', { name: 'Pace, from gentle to firm' })).toHaveValue('5');
	await shot(page, '15-training-setup');
	await card.getByRole('button', { name: 'Start sleep training' }).click();

	await expect(card).toContainText('Graduated extinction. Night 1.');
	await expect(card.getByRole('listitem').filter({ hasText: 'wait before each check' })).toContainText('2, 4, 6, 8, 10 minutes');
	await expect(card).toContainText('Scale: 5 of 10');
	await page.screenshot({ path: 'recordings/m2/screens/15-training-active-full.png', fullPage: true });
	await shot(page, '15-training-active');

	// A hard night: with the switch on, the scale goes one step to gentle for the next night.
	await card.getByLabel('Minutes from bed to asleep').fill('50');
	await card.getByLabel('Wakes in the night').fill('3');
	await card.getByRole('radio', { name: 'Too hard' }).check();
	await card.getByRole('button', { name: 'Save the night' }).click();
	await expect(card).toContainText('Night 2.');
	await expect(card).toContainText('Scale: 4 of 10');
	await expect(card).toContainText('50 min to sleep, 3 wakes, pace 5, too hard');

	// By hand: the firm end. No wait is longer than 15 minutes.
	await card.getByRole('radio', { name: 'Keep the scale. I change it by hand' }).check();
	await card.getByRole('slider', { name: 'Pace, from gentle to firm' }).fill('10');
	await expect(card.getByRole('listitem').filter({ hasText: 'wait before each check' })).toContainText('5, 10, 15 minutes, then 15 minutes each time');

	// A fever is logged: the page asks to pause.
	expect((await api.post(`children/${family.childId}/entries`, { data: { type: 'temperature', started_at: local(), data: { celsius: 38.4 } } })).ok()).toBeTruthy();
	await page.reload();
	await page.getByRole('tab', { name: 'Sleep plan' }).click();
	await expect(card).toContainText('Do not train when Mia is ill');
	await card.getByRole('button', { name: 'Pause' }).click();
	await expect(card).toContainText('Paused.');
	await card.getByRole('button', { name: 'End sleep training' }).click();
	await expect(card).toContainText('It is off now');
});
