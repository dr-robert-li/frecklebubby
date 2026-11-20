// Trackers: labels, colours and the form fields of each entry type (SPEC section 4).
import { fmtDur, fmtUnit, type UnitKind, type Units } from './format.svelte';

export type EntryType =
	| 'sleep' | 'nursing' | 'bottle' | 'solids' | 'nappy' | 'potty' | 'pump'
	| 'growth' | 'temperature' | 'medicine' | 'activity' | 'milestone' | 'note' | 'cry' | 'confined';

export type Entry = {
	id: number;
	child_id: number;
	type: EntryType;
	started_at: string;
	ended_at: string | null;
	data: Record<string, any>;
	notes: string | null;
	source: string;
	created_by: number | null;
};

export type Wording = 'nappy' | 'diaper';

type Opt = [value: string, label: string];
// more: shown under the collapsed "More details" part of the sheet.
type Common = { key: string; label: string; required?: boolean; show?: (v: any) => boolean; more?: boolean };
export type Field =
	| (Common & { kind: 'one' | 'many'; options: Opt[] })
	| (Common & { kind: 'num'; unit?: UnitKind | 'min'; plain?: string; max?: number; chips?: number[] })
	| (Common & { kind: 'text' | 'bool' | 'foods' });

export type Tracker = {
	type: EntryType;
	label: string;
	color: string; // CSS variable of the tracker pastel
	icon?: string; // Icon name when it is not the type
	end?: 'required' | 'optional';
	timer?: boolean;
	fields: Field[];
};

const CONDITIONS: Opt[] = [
	['happy', 'Happy'], ['upset', 'Upset'], ['under_10_minutes', 'Fell asleep in under 10 min'],
	['10-20_minutes', 'Fell asleep in 10–20 min'], ['longTimeToFallAsleep', 'Long time to fall asleep'],
	['wokeUpChild', 'I woke them']
];
const LOCATIONS: Opt[] = [
	['onOwnInBed', 'Own bed'], ['nursing', 'Nursing'], ['wornOrHeld', 'Held or worn'], ['nextToCarer', 'Next to carer'],
	['coSleep', 'Co-sleeping'], ['bottle', 'Bottle'], ['stroller', 'Pram'], ['car', 'Car'], ['swing', 'Swing']
];
export const MILK: Opt[] = [
	['Breast Milk', 'Breast milk'], ['Formula', 'Formula'], ['Tube Feeding', 'Tube feeding'], ['Cow Milk', 'Cow milk'],
	['Goat Milk', 'Goat milk'], ['Soy Milk', 'Soy milk'], ['Other', 'Other']
];
const REACTIONS: Opt[] = [['LOVED', 'Loved it'], ['MEH', 'Okay'], ['HATED', 'Did not like it'], ['ALLERGIC', 'Allergic reaction']];
const AMOUNTS: Opt[] = [['little', 'Little'], ['medium', 'Medium'], ['big', 'Big']];
export const POO_COLOURS: Opt[] = [
	['yellow', 'Yellow'], ['brown', 'Brown'], ['green', 'Green'], ['black', 'Black'], ['red', 'Red'], ['gray', 'Grey']
];
const CONSISTENCY: Opt[] = [
	['solid', 'Solid'], ['loose', 'Loose'], ['runny', 'Runny'], ['mucousy', 'Mucus'], ['hard', 'Hard'],
	['pebbles', 'Pebbles'], ['diarrhea', 'Diarrhoea']
];
const POTTY: Opt[] = [['wentPotty', 'Went in the potty'], ['satButDry', 'Sat, nothing'], ['accident', 'Accident']];
export const ACTIVITIES: Opt[] = [
	['bath', 'Bath'], ['tummyTime', 'Tummy time'], ['storyTime', 'Story time'], ['screenTime', 'Screen time'],
	['skinToSkin', 'Skin to skin'], ['outdoorPlay', 'Outdoor play'], ['indoorPlay', 'Indoor play'], ['brushTeeth', 'Brush teeth']
];
export const DEVICES: Opt[] = [
	['car_seat', 'Car seat'], ['pram', 'Pram'], ['bouncer', 'Bouncer'], ['swing', 'Swing'], ['carrier', 'Carrier'],
	['high_chair', 'High chair'], ['other', 'Other']
];
export const PEE_COLOURS: Opt[] = [
	['pale', 'Pale'], ['yellow', 'Yellow'], ['dark_yellow', 'Dark yellow'], ['orange_pink', 'Orange or pink'], ['red', 'Red']
];
const PEE_LOOK: Opt[] = [['clear', 'Clear'], ['cloudy', 'Cloudy']];
const RASH: Opt[] = [['mild', 'Mild'], ['moderate', 'Moderate'], ['severe', 'Severe']];
const MED_UNITS: Opt[] = [['ml', 'ml'], ['oz', 'oz'], ['tsp', 'tsp'], ['drops', 'drops'], ['mg', 'mg']];
const SIDES: Opt[] = [['left', 'Left'], ['right', 'Right']];

const pee = (v: any) => v.mode === 'pee' || v.mode === 'both';
const poo = (v: any) => v.mode === 'poo' || v.mode === 'both';
const nappyFields = (word: string): Field[] => [
	{ key: 'mode', label: 'Type', kind: 'one', required: true, options: [['pee', 'Wet'], ['poo', 'Dirty'], ['both', 'Wet and dirty'], ['dry', 'Dry']] },
	{ key: 'pee_amount', label: 'Wee amount', kind: 'one', options: AMOUNTS, show: pee, more: true },
	{ key: 'pee_color', label: 'Wee colour', kind: 'one', options: PEE_COLOURS, show: pee, more: true },
	{ key: 'pee_look', label: 'Wee looks', kind: 'one', options: PEE_LOOK, show: pee, more: true },
	{ key: 'pee_smell', label: 'Strong smell', kind: 'bool', show: pee, more: true },
	{ key: 'poo_amount', label: 'Poo amount', kind: 'one', options: AMOUNTS, show: poo, more: true },
	{ key: 'color', label: 'Poo colour', kind: 'one', options: POO_COLOURS, show: poo, more: true },
	{ key: 'consistency', label: 'Poo texture', kind: 'one', options: CONSISTENCY, show: poo, more: true },
	{ key: 'rash', label: `${word} rash`, kind: 'bool', more: true },
	{ key: 'rash_severity', label: 'How bad is the rash', kind: 'one', options: RASH, show: (v) => !!v.rash, more: true },
	{ key: 'air_minutes', label: `Air time (${word.toLowerCase()} off)`, kind: 'num', plain: 'min', max: 240, chips: [5, 10, 15, 30], more: true }
];

export function trackers(wording: Wording): Tracker[] {
	const Nappy = wording === 'diaper' ? 'Diaper' : 'Nappy';
	return [
		{ type: 'sleep', label: 'Sleep', color: '--lavender', end: 'required', timer: true, fields: [
			{ key: 'locations', label: 'Where', kind: 'many', options: LOCATIONS },
			{ key: 'start_conditions', label: 'Falling asleep', kind: 'many', options: CONDITIONS.filter((c) => c[0] !== 'wokeUpChild') },
			{ key: 'end_conditions', label: 'Waking up', kind: 'many', options: CONDITIONS.filter((c) => !c[0].includes('minutes') && c[0] !== 'longTimeToFallAsleep') }
		] },
		{ type: 'nursing', label: 'Nursing', color: '--rose', end: 'optional', timer: true, fields: [
			{ key: 'left_seconds', label: 'Left side', kind: 'num', unit: 'min', max: 240 },
			{ key: 'right_seconds', label: 'Right side', kind: 'num', unit: 'min', max: 240 },
			{ key: 'last_side', label: 'Last side', kind: 'one', options: SIDES }
		] },
		{ type: 'bottle', label: 'Bottle', color: '--sky', fields: [
			{ key: 'amount_ml', label: 'Amount', kind: 'num', unit: 'volume', required: true },
			{ key: 'milk_type', label: 'Milk', kind: 'one', options: MILK }
		] },
		{ type: 'nappy', label: Nappy, color: '--mint', fields: nappyFields(Nappy) },
		{ type: 'solids', label: 'Solids', color: '--butter', fields: [
			{ key: 'foods', label: 'Foods', kind: 'foods', required: true },
			{ key: 'reaction', label: 'Reaction', kind: 'one', options: REACTIONS }
		] },
		{ type: 'pump', label: 'Pump', color: '--rose', end: 'optional', timer: true, fields: [
			{ key: 'left_ml', label: 'Left', kind: 'num', unit: 'volume' },
			{ key: 'right_ml', label: 'Right', kind: 'num', unit: 'volume' },
			{ key: 'total_ml', label: 'Total (if not by side)', kind: 'num', unit: 'volume' }
		] },
		{ type: 'potty', label: 'Potty', color: '--mint', fields: [
			{ key: 'result', label: 'Result', kind: 'one', required: true, options: POTTY },
			...nappyFields(Nappy)
		] },
		{ type: 'medicine', label: 'Medicine', color: '--sky', fields: [
			{ key: 'name', label: 'Name', kind: 'text', required: true },
			{ key: 'amount', label: 'Amount', kind: 'num' },
			{ key: 'unit', label: 'Unit', kind: 'one', options: MED_UNITS }
		] },
		{ type: 'temperature', label: 'Temperature', color: '--peach', fields: [
			{ key: 'celsius', label: 'Temperature', kind: 'num', unit: 'temperature', required: true }
		] },
		{ type: 'growth', label: 'Growth', color: '--sage', fields: [
			{ key: 'weight_kg', label: 'Weight', kind: 'num', unit: 'weight' },
			{ key: 'height_cm', label: 'Length or height', kind: 'num', unit: 'length' },
			{ key: 'head_cm', label: 'Head', kind: 'num', unit: 'length' }
		] },
		{ type: 'activity', label: 'Activity', color: '--butter', end: 'optional', timer: true, fields: [
			{ key: 'kind', label: 'Activity', kind: 'one', required: true, options: ACTIVITIES }
		] },
		{ type: 'confined', label: 'Confined', color: '--sand', end: 'optional', timer: true, fields: [
			{ key: 'device', label: 'Where', kind: 'one', required: true, options: DEVICES }
		] },
		{ type: 'milestone', label: 'Milestone', color: '--lavender', fields: [
			{ key: 'title', label: 'What happened', kind: 'text', required: true }
		] },
		{ type: 'note', label: 'Note', color: '--cloud', fields: [] },
		{ type: 'cry', label: 'Crying', color: '--coral', end: 'optional', fields: [
			{ key: 'soothed_by', label: 'What helped', kind: 'text' }
		] }
	];
}

export function tracker(type: string, wording: Wording): Tracker {
	return trackers(wording).find((t) => t.type === type)!;
}

function label(opts: Opt[], v: string) {
	return opts.find((o) => o[0] === v)?.[1] ?? v;
}

/** One line for the timeline, e.g. "120 ml · Formula". */
export function entryDetail(e: Entry, u: Units, wording: Wording): string {
	const d = e.data;
	const dur = e.ended_at ? fmtDur((Date.parse(e.ended_at) - Date.parse(e.started_at)) / 1000) : '';
	const parts: (string | false | undefined)[] = [];
	switch (e.type) {
		case 'sleep':
			parts.push(dur, ...(d.locations ?? []).map((l: string) => label(LOCATIONS, l)));
			break;
		case 'nursing':
			parts.push(
				d.left_seconds != null && `Left ${fmtDur(d.left_seconds)}`,
				d.right_seconds != null && `Right ${fmtDur(d.right_seconds)}`,
				d.left_seconds == null && d.right_seconds == null && dur
			);
			break;
		case 'bottle':
			parts.push(fmtUnit('volume', d.amount_ml, u), d.milk_type && label(MILK, d.milk_type));
			break;
		case 'solids':
			parts.push((d.foods ?? []).map((f: any) => (f.amount ? `${f.name} (${f.amount})` : f.name)).join(', '),
				d.reaction && label(REACTIONS, d.reaction));
			break;
		case 'potty':
			parts.push(label(POTTY, d.result));
		// falls through: potty has the nappy fields too
		case 'nappy':
			parts.push(
				{ pee: 'Wet', poo: 'Dirty', both: 'Wet and dirty', dry: 'Dry' }[d.mode as string],
				d.color && label(POO_COLOURS, d.color),
				d.consistency && label(CONSISTENCY, d.consistency),
				d.pee_color && `Wee ${label(PEE_COLOURS, d.pee_color).toLowerCase()}`,
				d.pee_look === 'cloudy' && 'Cloudy',
				d.pee_smell && 'Strong smell',
				d.rash && (d.rash_severity ? `Rash (${d.rash_severity})` : 'Rash'),
				d.air_minutes && `Air time ${d.air_minutes} min`
			);
			break;
		case 'confined':
			parts.push(label(DEVICES, d.device), dur);
			break;
		case 'pump':
			parts.push(d.total_ml != null && fmtUnit('volume', d.total_ml, u),
				d.left_ml != null && `Left ${fmtUnit('volume', d.left_ml, u)}`,
				d.right_ml != null && `Right ${fmtUnit('volume', d.right_ml, u)}`, dur);
			break;
		case 'growth':
			parts.push(d.weight_kg != null && fmtUnit('weight', d.weight_kg, u),
				d.height_cm != null && fmtUnit('length', d.height_cm, u),
				d.head_cm != null && `Head ${fmtUnit('length', d.head_cm, u)}`);
			break;
		case 'temperature':
			parts.push(fmtUnit('temperature', d.celsius, u));
			break;
		case 'medicine':
			parts.push(d.name, d.amount != null && `${d.amount} ${d.unit ?? ''}`.trim());
			break;
		case 'activity':
			parts.push(label(ACTIVITIES, d.kind), dur);
			break;
		case 'milestone':
			parts.push(d.title);
			break;
		case 'cry':
			parts.push(dur, d.soothed_by && `Helped: ${d.soothed_by}`,
				d.sound_reason && `Sound guess: ${soundLabel(d.sound_reason)} (experimental)`);
			break;
	}
	if (e.type === 'note' || (e.notes && !parts.some(Boolean))) parts.push(e.notes ?? '');
	return parts.filter(Boolean).join(' · ');
}

/** Cry helper labels. */
export const SOUND_LABELS: Record<string, string> = {
	hungry: 'Hungry', tired: 'Tired', burping: 'Needs burping', belly_pain: 'Belly pain', discomfort: 'Discomfort',
	scared: 'Scared'
};
export const soundLabel = (v: string) => SOUND_LABELS[v] ?? v;

export function needLabel(need: string, wording: Wording): string {
	const labels: Record<string, string> = {
		hunger: 'Hungry', tired: 'Tired', nappy: wording === 'diaper' ? 'Diaper' : 'Nappy', wind: 'Wind',
		unwell: 'May be unwell', allergic: 'Allergic reaction', too_hot_or_cold: 'Too hot or too cold',
		cuddle: 'Wants comfort', evening_crying: 'Evening crying', colic: 'Colic pattern'
	};
	return labels[need] ?? need;
}

export const deviceLabel = (v: string) => label(DEVICES, v);

export function activityLabel(kind: string) {
	return label(ACTIVITIES, kind);
}
