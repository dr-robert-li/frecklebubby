// Time, units and wording. Storage is UTC, ml, kg, cm, °C; we convert only for display and input.

export type Units = { volume: 'ml' | 'oz'; weight: 'kg' | 'lb'; length: 'cm' | 'in'; temperature: 'C' | 'F' };
export type UnitKind = keyof Units;

export const prefs = $state({ tz: 'UTC', clock24: true });

function parts(d: Date, tz = prefs.tz) {
	const p: Record<string, string> = {};
	for (const x of new Intl.DateTimeFormat('en-AU', {
		timeZone: tz,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		hourCycle: 'h23'
	}).formatToParts(d))
		p[x.type] = x.value;
	return p;
}

/** "YYYY-MM-DDTHH:MM" in the family time zone, for datetime-local inputs. The API reads it in the same zone. */
export function toLocalInput(iso?: string | number | Date): string {
	const p = parts(iso === undefined ? new Date() : new Date(iso));
	return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** Local calendar day "YYYY-MM-DD" in the family time zone. */
export function localDay(iso?: string | number | Date): string {
	return toLocalInput(iso).slice(0, 10);
}

export function addDays(day: string, n: number): string {
	const d = new Date(day + 'T12:00:00Z');
	d.setUTCDate(d.getUTCDate() + n);
	return d.toISOString().slice(0, 10);
}

export function fmtTime(iso: string | number | Date): string {
	return new Intl.DateTimeFormat('en-AU', {
		timeZone: prefs.tz,
		hour: 'numeric',
		minute: '2-digit',
		hourCycle: prefs.clock24 ? 'h23' : 'h12'
	}).format(new Date(iso));
}

export function fmtDay(day: string, opts: Intl.DateTimeFormatOptions = { weekday: 'long', day: 'numeric', month: 'long' }) {
	return new Intl.DateTimeFormat('en-AU', { ...opts, timeZone: 'UTC' }).format(new Date(day + 'T12:00:00Z'));
}

export function fmtDayLabel(day: string): string {
	const today = localDay();
	if (day === today) return 'Today';
	if (day === addDays(today, -1)) return 'Yesterday';
	return fmtDay(day);
}

/** "1 h 05 min", "12 min", "40 s". */
export function fmtDur(seconds: number): string {
	const s = Math.max(0, Math.round(seconds));
	if (s < 60) return s ? `${s} s` : '0 min';
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`;
}

/** Stopwatch "1:05:09" or "5:09". */
export function fmtClock(seconds: number): string {
	const s = Math.max(0, Math.floor(seconds));
	const h = Math.floor(s / 3600);
	const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, '0');
	const ss = String(s % 60).padStart(2, '0');
	return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtAgo(iso: string, now = Date.now()): string {
	const min = Math.round((now - Date.parse(iso)) / 60000);
	if (min < 1) return 'just now';
	if (min < 60) return `${min} min ago`;
	const h = Math.floor(min / 60);
	if (h < 24) return `${h} h ${min % 60} min ago`;
	const d = Math.floor(h / 24);
	return d === 1 ? 'yesterday' : `${d} days ago`;
}

export function ageText(birthdate: string): string {
	const b = new Date(birthdate + 'T00:00:00Z');
	const t = new Date(localDay() + 'T00:00:00Z');
	const days = Math.round((+t - +b) / 86400000);
	if (days < 0) return 'Not born yet';
	if (days < 14) return `${days} ${days === 1 ? 'day' : 'days'} old`;
	if (days < 90) return `${Math.floor(days / 7)} weeks old`;
	let months = (t.getUTCFullYear() - b.getUTCFullYear()) * 12 + t.getUTCMonth() - b.getUTCMonth();
	if (t.getUTCDate() < b.getUTCDate()) months--;
	if (months < 24) return `${months} months old`;
	return `${Math.floor(months / 12)} years old`;
}

// --- units -------------------------------------------------------------------------------------

const FACTOR = { volume: 29.5735, weight: 0.45359237, length: 2.54 };

/** Canonical value (ml, kg, cm, °C) to the family unit. */
export function toUnit(kind: UnitKind, v: number, u: Units): number {
	if (kind === 'temperature') return u.temperature === 'F' ? (v * 9) / 5 + 32 : v;
	const metric = { volume: 'ml', weight: 'kg', length: 'cm' }[kind];
	return u[kind] === metric ? v : v / FACTOR[kind];
}

/** Family unit back to canonical. */
export function fromUnit(kind: UnitKind, v: number, u: Units): number {
	if (kind === 'temperature') return u.temperature === 'F' ? ((v - 32) * 5) / 9 : v;
	const metric = { volume: 'ml', weight: 'kg', length: 'cm' }[kind];
	return u[kind] === metric ? v : v * FACTOR[kind];
}

export function unitLabel(kind: UnitKind, u: Units): string {
	return kind === 'temperature' ? `°${u.temperature}` : u[kind];
}

const DECIMALS: Record<string, number> = { ml: 0, oz: 1, kg: 2, lb: 2, cm: 1, in: 1, C: 1, F: 1 };

export function round(kind: UnitKind, v: number, u: Units): number {
	const d = DECIMALS[u[kind]];
	return Math.round(v * 10 ** d) / 10 ** d;
}

/** "120 ml", "4.1 oz", "37.2 °C". */
export function fmtUnit(kind: UnitKind, v: number, u: Units): string {
	const n = round(kind, toUnit(kind, v, u), u);
	return kind === 'temperature' ? `${n} °${u.temperature}` : `${n} ${u[kind]}`;
}
