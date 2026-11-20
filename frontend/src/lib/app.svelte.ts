// Shared app state: signed-in user, family, settings, the selected child and its live status.
import { api, type Config } from './api';
import { localDay, prefs, type Units } from './format.svelte';
import type { Entry, Wording } from './trackers';

export type Child = {
	id: number;
	name: string;
	birthdate: string;
	/** Due date of a baby born early (M13): development uses the corrected age until 2 years. */
	due_date?: string | null;
	sex: 'F' | 'M' | null;
	color: string;
	night_start: string;
	morning_cutoff: string;
	archived: boolean;
};
export type Timer = {
	type: string;
	started_at: string;
	paused_at: string | null;
	paused_seconds: number;
	data: Record<string, any>;
};
export type Prediction = { start: string; end: string; kind: 'nap' | 'bedtime'; basis: string; note: string };
export type ConfinedLevel = { after_seconds: number; title: string; text: string; citations: any[] };
export type Status = {
	now: string;
	timers: Timer[];
	last: Record<string, Entry>;
	today: any;
	prediction: Prediction | null;
	unread_notifications: number;
	/** Set while a confined timer runs: the continuous period and the texts for this child's age. */
	confined: { since: string; device: string; seconds: number; note: ConfinedLevel | null; warning: ConfinedLevel | null } | null;
};
export type Settings = {
	units: Units;
	wording: Wording;
	llm: { base_url: string; model: string; has_api_key: boolean };
	web_lookup: boolean;
	milestone_alerts: boolean;
};
type Me = {
	user: { id: number; email: string; name: string };
	family: { id: number; name: string; timezone: string } | null;
	role: 'owner' | 'carer' | null;
	children: Child[];
};

const CHILD_KEY = 'fb.child';

export const app = $state({
	config: null as Config | null,
	me: null as Me | null,
	settings: null as Settings | null,
	childId: null as number | null,
	status: null as Status | null,
	today: [] as Entry[],
	skew: 0, // server clock minus device clock, ms
	now: Date.now(),
	toast: ''
});

export const child = () => app.me?.children.find((c) => c.id === app.childId) ?? null;
export const units = (): Units => app.settings?.units ?? { volume: 'ml', weight: 'kg', length: 'cm', temperature: 'C' };
export const wording = (): Wording => app.settings?.wording ?? 'nappy';
/** Server-aligned "now" in ms. Ticks every second. */
export const serverNow = () => app.now + app.skew;

export async function loadMe() {
	app.me = await api<Me>('/me');
	if (!app.me.family) return;
	prefs.tz = app.me.family.timezone;
	app.settings = await api<Settings>('/family/settings');
	const saved = Number(localStorage.getItem(CHILD_KEY));
	const ids = app.me.children.map((c) => c.id);
	app.childId = ids.includes(saved) ? saved : (ids[0] ?? null);
}

export function selectChild(id: number) {
	app.childId = id;
	localStorage.setItem(CHILD_KEY, String(id));
	app.status = null;
	app.today = [];
	refresh();
}

let inflight = false;
/** Reload status and today's entries of the selected child. */
export async function refresh() {
	const id = app.childId;
	if (!id || inflight) return;
	inflight = true;
	try {
		const [status, today] = await Promise.all([
			api<Status>(`/children/${id}/status`),
			api<Entry[]>(`/children/${id}/entries?from=${localDay()}T00:00&limit=200`)
		]);
		if (id !== app.childId) return;
		// Server times are whole seconds; correct only a real clock difference, not the rounding.
		const skew = Date.parse(status.now) - Date.now();
		app.skew = Math.abs(skew) > 2000 ? skew : 0;
		app.status = status;
		app.today = today;
	} catch {
		/* keep the last good state; the next poll tries again */
	} finally {
		inflight = false;
	}
}

let toastTimer: ReturnType<typeof setTimeout>;
export function toast(msg: string) {
	app.toast = msg;
	clearTimeout(toastTimer);
	toastTimer = setTimeout(() => (app.toast = ''), 3500);
}

export function elapsed(t: Timer): number {
	const end = t.paused_at ? Date.parse(t.paused_at) : serverNow();
	return (end - Date.parse(t.started_at)) / 1000 - t.paused_seconds;
}

/** Tummy time seconds of a play timer, live. */
export function tummySeconds(t: Timer): number {
	const d = t.data;
	return (d.tummy_seconds ?? 0) + (d.tummy_started_at ? (serverNow() - Date.parse(d.tummy_started_at)) / 1000 : 0);
}

/** Seconds on each nursing side, live. */
export function sideSeconds(t: Timer): { left: number; right: number } {
	const d = t.data;
	const live = d.side_since ? (serverNow() - Date.parse(d.side_since)) / 1000 : 0;
	return {
		left: (d.left_seconds ?? 0) + (d.side === 'left' ? live : 0),
		right: (d.right_seconds ?? 0) + (d.side === 'right' ? live : 0)
	};
}
