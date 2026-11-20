import { expect, openTile, shot, test } from './fixtures';

const seconds = (s: string) => s.split(':').map(Number).reduce((a, b) => a * 60 + b, 0);

test('sleep timer keeps running after a reload and saves an entry', async ({ page, family }) => {
	await page.goto('/');
	const sheet = await openTile(page, 'Sleep');
	await shot(page, '02-sleep-sheet');
	await sheet.getByRole('button', { name: 'Start sleep timer' }).click();

	const timer = page.getByRole('region', { name: 'Sleep timer' });
	await expect(timer).toBeVisible();
	await expect(timer.getByText('Running')).toBeVisible();
	await page.waitForTimeout(2500);

	await page.reload();
	await expect(timer).toBeVisible();
	const clock = timer.getByRole('timer');
	expect(seconds(await clock.innerText())).toBeGreaterThanOrEqual(2);
	await shot(page, '02-sleep-running');

	await timer.getByRole('button', { name: 'Stop and save' }).click();
	await expect(timer).toBeHidden();
	await expect(page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Sleep/ })).toBeVisible();
	await shot(page, '02-sleep-saved');
});

test('nursing timer switches side, pauses and resumes', async ({ page, family }) => {
	await page.goto('/');
	const sheet = await openTile(page, 'Breastfeeding');
	await sheet.getByRole('button', { name: 'Start left' }).click();

	const timer = page.getByRole('region', { name: 'Breastfeeding timer' });
	await expect(timer.getByText('Left (now)')).toBeVisible();
	await page.waitForTimeout(1500);
	await timer.getByRole('button', { name: 'Switch side' }).click();
	await expect(timer.getByText('Right (now)')).toBeVisible();
	await page.waitForTimeout(1200);

	await timer.getByRole('button', { name: 'Pause' }).click();
	await expect(timer.getByText(/Paused/)).toBeVisible();
	const paused = await timer.getByRole('timer').innerText();
	await page.waitForTimeout(1500);
	await expect(timer.getByRole('timer')).toHaveText(paused);
	await shot(page, '03-nursing-paused');

	await timer.getByRole('button', { name: 'Resume' }).click();
	await expect(timer.getByText(/Running/)).toBeVisible();
	await timer.getByRole('button', { name: 'Stop and save' }).click();

	const item = page.getByRole('list', { name: 'Timeline' }).getByRole('button', { name: /Edit Breastfeeding/ });
	await expect(item).toContainText('Left');
	await expect(item).toContainText('Right');
	await shot(page, '03-nursing-saved');
});
