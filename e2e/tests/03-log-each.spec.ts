import { expect, local, openTile, shot, test, todayAgo, type Page } from './fixtures';

const timeline = (page: Page) => page.getByRole('list', { name: 'Timeline' });

async function expectLogged(page: Page, label: string, text: string | RegExp) {
	await expect(page.getByRole('dialog')).toBeHidden();
	await expect(timeline(page).getByRole('button', { name: new RegExp(`Edit ${label}`) }).first()).toContainText(text);
}

test('a parent logs each kind of entry and sees it in the timeline', async ({ page, family }) => {
	await page.goto('/');

	// bottle
	let s = await openTile(page, 'Bottle');
	await s.getByLabel('Amount (ml)').fill('120');
	await s.getByRole('button', { name: 'Formula', exact: true }).click();
	await shot(page, '04-bottle-sheet');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Bottle', '120 ml · Formula');

	// nappy: poo with colour and texture
	s = await openTile(page, 'Nappy');
	await s.getByRole('button', { name: 'Dirty', exact: true }).click();
	await s.getByText('More details').click(); // details are collapsed so that the quick log stays 2 taps (M9)
	await s.getByRole('button', { name: 'Yellow' }).click();
	await s.getByRole('button', { name: 'Runny' }).click();
	await s.getByRole('button', { name: 'Big' }).click();
	await shot(page, '04-nappy-sheet');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Nappy', 'Dirty · Yellow · Runny');

	// solids
	s = await openTile(page, 'Solids');
	await s.getByLabel('Food 1', { exact: true }).fill('Pumpkin');
	await s.getByLabel('Amount of food 1').fill('2 spoons');
	await s.getByRole('button', { name: 'Add food' }).click();
	await s.getByLabel('Food 2', { exact: true }).fill('Pear');
	await s.getByRole('button', { name: 'Loved it' }).click();
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Solids', 'Pumpkin (2 spoons), Pear · Loved it');

	// pump (a past session)
	s = await openTile(page, 'Pump');
	await s.getByRole('tab', { name: 'Log a past one' }).click();
	await s.getByLabel('Left (ml)').fill('60');
	await s.getByLabel('Right (ml)').fill('50');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Pump', '110 ml · Left 60 ml · Right 50 ml');

	// potty
	s = await openTile(page, 'Potty');
	await s.getByRole('button', { name: 'Went in the potty' }).click();
	await s.getByRole('button', { name: 'Wet', exact: true }).click();
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Potty', 'Went in the potty · Wet');

	// medicine
	s = await openTile(page, 'Medicine');
	await s.getByLabel('Name').fill('Paracetamol');
	await s.getByLabel('Amount', { exact: true }).fill('2.5');
	await s.getByRole('button', { name: 'ml', exact: true }).click();
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Medicine', 'Paracetamol · 2.5 ml');

	// temperature
	s = await openTile(page, 'Temperature');
	await s.getByLabel('Temperature (°C)').fill('37.4');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Temperature', '37.4 °C');

	// growth
	s = await openTile(page, 'Growth');
	await s.getByLabel('Weight (kg)').fill('6.8');
	await s.getByLabel('Length or height (cm)').fill('64');
	await s.getByLabel('Head (cm)').fill('41.5');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Growth', '6.8 kg · 64 cm · Head 41.5 cm');

	// activity (a past bath)
	s = await openTile(page, 'Activity');
	await s.getByRole('tab', { name: 'Log a past one' }).click();
	await s.getByRole('button', { name: 'Bath' }).click();
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Activity', 'Bath');

	// milestone
	s = await openTile(page, 'Milestone');
	await s.getByLabel('What happened').fill('First laugh');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Milestone', 'First laugh');

	// note
	s = await openTile(page, 'Note');
	await s.getByRole('button', { name: 'Save' }).click();
	await expect(s.getByRole('alert')).toHaveText('Write a note.');
	await s.getByLabel('Note').fill('Grandma visited');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Note', 'Grandma visited');

	// bath: log, edit, delete
	s = await openTile(page, 'Bath');
	await s.getByLabel('Notes (optional)').fill('Warm water');
	await shot(page, '04-bath-sheet');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Bath', 'Warm water');
	const bath = timeline(page).getByRole('button', { name: /Edit Bath/ });
	await bath.click();
	await expect(s.getByRole('heading', { name: 'Edit bath' })).toBeVisible();
	await s.getByLabel('Notes (optional)').fill('Hair wash');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Bath', 'Hair wash');
	await bath.click();
	await s.getByRole('button', { name: 'Delete entry' }).click();
	await s.getByRole('button', { name: 'Yes, delete' }).click();
	await expect(bath).toHaveCount(0);

	// a sleep logged afterwards, with where and how
	s = await openTile(page, 'Sleep');
	await s.getByRole('tab', { name: 'Log a past one' }).click();
	const [start, end] = [todayAgo(25), local()];
	const mins = (Date.parse(`${end}Z`) - Date.parse(`${start}Z`)) / 60_000;
	await s.getByLabel('Start').fill(start);
	await s.getByLabel('End').fill(end);
	await s.getByRole('button', { name: 'Own bed' }).click();
	await s.getByRole('button', { name: 'Happy' }).first().click();
	await shot(page, '04-sleep-past-sheet');
	await s.getByRole('button', { name: 'Save' }).click();
	await expectLogged(page, 'Sleep', `${mins} min · Own bed`);

	await expect(timeline(page).getByRole('listitem')).toHaveCount(12);
	await shot(page, '04-home-timeline', true);
});
