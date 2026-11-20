<script lang="ts">
	// Log, edit or delete one entry of any type. Timer types also get a "Start timer" tab.
	import { api } from './api';
	import { app, refresh, toast, units, wording } from './app.svelte';
	import Cites from './Cites.svelte';
	import { fromUnit, round, toLocalInput, toUnit, unitLabel, type UnitKind } from './format.svelte';
	import Icon from './Icon.svelte';
	import Sheet from './Sheet.svelte';
	import { ACTIVITIES, activityLabel, DEVICES, tracker, type Entry, type EntryType, type Field } from './trackers';

	let { type, entry = null, childId, onclose }: { type: EntryType; entry?: Entry | null; childId: number; onclose: () => void } =
		$props();

	const t = $derived(tracker(type, wording()));
	const u = units();
	// Activity timers run in parallel, one per kind: another kind can start while one runs.
	const runningKinds = $derived((app.status?.timers ?? []).filter((x) => x.type === 'activity').map((x) => x.data.kind));
	const running = $derived(type !== 'activity' && app.status?.timers.some((x) => x.type === type));
	const POO_HEX: Record<string, string> = { yellow: '#E8C547', brown: '#8A5A2B', green: '#6E9B3A', black: '#222', red: '#C0392B', gray: '#9A9A9A' };
	const PEE_HEX: Record<string, string> = { pale: '#F7F1C8', yellow: '#F2D74E', dark_yellow: '#C9971C', orange_pink: '#F2A07B', red: '#C0392B' };
	const HEX: Record<string, Record<string, string>> = { color: POO_HEX, pee_color: PEE_HEX };

	// form values in display units
	function initial(): Record<string, any> {
		const d = entry?.data ?? {};
		const last = app.status?.last[type]?.data ?? {};
		const v: Record<string, any> = {};
		for (const f of tracker(type, wording()).fields) {
			let x = d[f.key];
			if (f.kind === 'num' && x != null) x = f.unit === 'min' ? Math.round(x / 6) / 10 : f.unit ? round(f.unit, toUnit(f.unit, x, u), u) : x;
			v[f.key] = x ?? (f.kind === 'many' ? [] : f.kind === 'foods' ? [{ name: '', amount: '' }] : f.kind === 'bool' ? false : '');
		}
		if (!entry) {
			// sensible defaults: repeat the last bottle or medicine, wet nappy
			if (type === 'bottle' && last.amount_ml) Object.assign(v, { amount_ml: round('volume', toUnit('volume', last.amount_ml, u), u), milk_type: last.milk_type ?? '' });
			if (type === 'medicine' && last.name) Object.assign(v, { name: last.name, amount: last.amount ?? '', unit: last.unit ?? '' });
			if (type === 'nappy') v.mode = 'pee';
		}
		return v;
	}

	// The form starts from the entry (or defaults) once; later prop changes do not reset it.
	const start = () => ({
		notes: entry?.notes ?? '',
		started: toLocalInput(entry?.started_at ?? (type === 'sleep' && !entry ? Date.now() - 3600_000 : undefined)),
		ended: entry?.ended_at ? toLocalInput(entry.ended_at) : type === 'sleep' ? toLocalInput() : '',
		tab: (t.timer && !entry && !running ? 'timer' : 'log') as 'timer' | 'log',
		more: !!entry && t.fields.some((f) => f.more && entry!.data[f.key] != null && entry!.data[f.key] !== false)
	});
	const s0 = start();
	let vals = $state(initial());
	let notes = $state(s0.notes);
	let started = $state(s0.started);
	let ended = $state(s0.ended);
	let tab = $state(s0.tab);
	let error = $state('');
	let busy = $state(false);
	let confirmDelete = $state(false);
	// "More details" starts open when the entry being edited has one of them.
	let moreOpen = $state(s0.more);
	let advice = $state<{ title: string; body: string; citations: any[] } | null>(null);

	const visible = (f: Field) => !f.show || f.show(vals);
	const empty = (x: any) => x === '' || x == null || (Array.isArray(x) && !x.length);

	function toggle(f: Field, value: string) {
		if (f.kind === 'many') {
			const a: string[] = vals[f.key];
			vals[f.key] = a.includes(value) ? a.filter((x) => x !== value) : [...a, value];
		} else vals[f.key] = vals[f.key] === value && !f.required ? '' : value;
	}

	function buildData(): Record<string, any> | null {
		// Keep data the form does not show (for example the cry helper's sound fields): PATCH replaces all data.
		const shown = new Set(t.fields.map((f) => f.key));
		const data: Record<string, any> = Object.fromEntries(Object.entries(entry?.data ?? {}).filter(([k]) => !shown.has(k)));
		for (const f of t.fields) {
			if (!visible(f)) continue;
			let x = vals[f.key];
			if (f.kind === 'foods') x = x.filter((fd: any) => fd.name.trim()).map((fd: any) => (fd.amount.trim() ? { name: fd.name.trim(), amount: fd.amount.trim() } : { name: fd.name.trim() }));
			if (f.kind === 'text' && typeof x === 'string') x = x.trim();
			if (f.kind === 'bool') {
				if (x || !f.more) data[f.key] = !!x; // optional details: leave out when not ticked
				continue;
			}
			if (empty(x)) {
				if (f.required) {
					error = `Add ${f.label.toLowerCase()}.`;
					return null;
				}
				continue;
			}
			if (f.kind === 'num') {
				const n = Number(x);
				if (!Number.isFinite(n) || n < 0) {
					error = `${f.label}: give a number.`;
					return null;
				}
				x = f.unit === 'min' ? Math.round(n * 60) : f.unit ? fromUnit(f.unit as UnitKind, n, u) : n;
				if (f.unit && f.unit !== 'min' && f.unit !== 'temperature') x = Math.round(x * 1000) / 1000;
				if (f.unit === 'temperature') x = Math.round(x * 100) / 100;
			}
			data[f.key] = x;
		}
		if (type === 'growth' && !Object.keys(data).length) {
			error = 'Add weight, length or head size.';
			return null;
		}
		return data;
	}

	async function save() {
		error = '';
		const data = buildData();
		if (!data) return;
		if (type === 'note' && !notes.trim()) return void (error = 'Write a note.');
		if (t.end === 'required' && !ended) return void (error = 'Add the end time.');
		const body: Record<string, any> = { started_at: started, data, notes: notes.trim() || null };
		if (t.end) body.ended_at = ended || null;
		busy = true;
		try {
			if (entry) await api(`/entries/${entry.id}`, { method: 'PATCH', body });
			else await api(`/children/${childId}/entries`, { method: 'POST', body: { type, ...body } });
			toast(entry ? 'Changes saved' : `${t.label} saved`);
			refresh();
			if (data.rash && (type === 'nappy' || type === 'potty') && (await showRashAdvice())) return;
			onclose();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	/** After a rash is logged: show the rash card from the insights (NHS advice with sources). */
	async function showRashAdvice() {
		try {
			const cards = await api<any[]>(`/children/${childId}/insights`);
			advice = cards.find((c) => c.kind === 'nappy_rash') ?? null;
		} catch {
			advice = null;
		}
		return !!advice;
	}

	async function remove() {
		busy = true;
		try {
			await api(`/entries/${entry!.id}`, { method: 'DELETE' });
			toast('Entry deleted');
			refresh();
			onclose();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	async function startTimer(extra: Record<string, string> = {}) {
		if (type === 'activity' && !vals.kind) return void (error = 'Choose an activity.');
		if (type === 'confined' && !vals.device) return void (error = 'Choose where.');
		busy = true;
		try {
			const body = type === 'activity' ? { kind: vals.kind } : type === 'confined' ? { device: vals.device } : extra;
			await api(`/children/${childId}/timers/${type}/start`, { method: 'POST', body });
			toast(`${type === 'activity' ? activityLabel(vals.kind) : t.label} timer started`);
			refresh();
			onclose();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

{#snippet fieldView(f: Field)}
			{#if f.kind === 'one' || f.kind === 'many'}
				<fieldset>
					<legend class="field-label">{f.label}</legend>
					<div class="chips">
						{#each f.options as [v, l] (v)}
							<button type="button" class="chip" aria-pressed={f.kind === 'many' ? vals[f.key].includes(v) : vals[f.key] === v}
								onclick={() => toggle(f, v)}>
								{#if HEX[f.key]}<span class="dot" style="background:{HEX[f.key][v]}"></span>{/if}{l}
							</button>
						{/each}
					</div>
				</fieldset>
			{:else if f.kind === 'num'}
				<label class="field"><span>{f.label}{f.unit ? ` (${f.unit === 'min' ? 'min' : unitLabel(f.unit, u)})` : f.plain ? ` (${f.plain})` : ''}</span>
					<input type="number" inputmode="decimal" step="any" min="0" max={f.max} bind:value={vals[f.key]} /></label>
				{#if f.chips}
					<div class="chips quick" role="group" aria-label="{f.label}: quick choice">
						{#each f.chips as c (c)}
							<button type="button" class="chip" aria-pressed={Number(vals[f.key]) === c} onclick={() => (vals[f.key] = Number(vals[f.key]) === c ? '' : c)}>{c} {f.plain ?? ''}</button>
						{/each}
					</div>
				{/if}
			{:else if f.kind === 'text'}
				<label class="field"><span>{f.label}</span><input type="text" maxlength="100" bind:value={vals[f.key]} /></label>
			{:else if f.kind === 'bool'}
				<label class="check"><input type="checkbox" bind:checked={vals[f.key]} /> {f.label}</label>
			{:else if f.kind === 'foods'}
				<fieldset>
					<legend class="field-label">{f.label}</legend>
					{#each vals.foods as food, i (i)}
						<div class="food">
							<input aria-label="Food {i + 1}" placeholder="Food, e.g. pumpkin" bind:value={food.name} />
							<input aria-label="Amount of food {i + 1}" placeholder="Amount" class="amt" bind:value={food.amount} />
							{#if vals.foods.length > 1}
								<button type="button" class="icon" aria-label="Remove food {i + 1}" onclick={() => vals.foods.splice(i, 1)}><Icon name="close" /></button>
							{/if}
						</div>
					{/each}
					<button type="button" class="plain" onclick={() => vals.foods.push({ name: '', amount: '' })}><Icon name="plus" /> Add food</button>
				</fieldset>
			{/if}
{/snippet}

<Sheet title={advice ? advice.title : entry ? `Edit ${t.label.toLowerCase()}` : t.label} {onclose}>
	{#if advice}
		<div class="stack advice" role="status">
			<p>{advice.body}</p>
			<Cites list={advice.citations} />
			<button class="wide big" style="background: var({t.color})" onclick={onclose}><Icon name="check" /> Done</button>
		</div>
	{:else}
	{#if t.timer && !entry}
		<div class="seg" role="tablist" aria-label="How to log">
			<button role="tab" aria-selected={tab === 'timer'} onclick={() => (tab = 'timer')}>Start timer</button>
			<button role="tab" aria-selected={tab === 'log'} onclick={() => (tab = 'log')}>Log a past one</button>
		</div>
	{/if}

	{#if tab === 'timer'}
		<div class="stack timer">
			{#if running}
				<p class="notice">A {t.label.toLowerCase()} timer is running. You can stop it on Home.</p>
			{:else if type === 'nursing'}
				<p class="muted">Which side do you start on?</p>
				<div class="two">
					<button class="big" style="background: var(--rose)" disabled={busy} onclick={() => startTimer({ side: 'left' })}>Start left</button>
					<button class="big" style="background: var(--rose)" disabled={busy} onclick={() => startTimer({ side: 'right' })}>Start right</button>
				</div>
			{:else}
				{#if type === 'activity'}
					<div class="chips" role="group" aria-label="Activity">
						{#each ACTIVITIES as [v, l] (v)}
							<button class="chip" aria-pressed={vals.kind === v} disabled={runningKinds.includes(v)}
								onclick={() => (vals.kind = v)}>{l}{runningKinds.includes(v) ? ' (running)' : ''}</button>
						{/each}
					</div>
				{:else if type === 'confined'}
					<p class="muted">Where is {app.me?.children.find((c) => c.id === childId)?.name ?? 'your child'}?</p>
					<div class="chips" role="group" aria-label="Where">
						{#each DEVICES as [v, l] (v)}
							<button class="chip" aria-pressed={vals.device === v} onclick={() => (vals.device = v)}>{l}</button>
						{/each}
					</div>
				{/if}
				<button class="big wide" style="background: var({t.color})" disabled={busy} onclick={() => startTimer()}>
					<Icon name="play" /> Start {t.label.toLowerCase()} timer
				</button>
			{/if}
			{#if error}<p class="error" role="alert">{error}</p>{/if}
		</div>
	{:else}
		<form class="stack" onsubmit={(e) => (e.preventDefault(), save())}>
			<div class="times">
				<label class="field"><span>{t.end ? 'Start' : 'Time'}</span>
					<input type="datetime-local" bind:value={started} required /></label>
				{#if t.end}
					<label class="field"><span>End{t.end === 'optional' ? ' (optional)' : ''}</span>
						<input type="datetime-local" bind:value={ended} required={t.end === 'required'} /></label>
				{/if}
			</div>

			{#each t.fields.filter((f) => !f.more) as f (f.key)}
				{#if visible(f)}{@render fieldView(f)}{/if}
			{/each}
			{#if t.fields.some((f) => f.more && visible(f))}
				<details class="more" bind:open={moreOpen}>
					<summary>More details <Icon name="down" /></summary>
					<div class="stack">
						{#each t.fields.filter((f) => f.more) as f (f.key)}
							{#if visible(f)}{@render fieldView(f)}{/if}
						{/each}
					</div>
				</details>
			{/if}

			<label class="field"><span>{type === 'note' ? 'Note' : 'Notes (optional)'}</span>
				<textarea bind:value={notes} maxlength="2000"></textarea></label>

			{#if error}<p class="error" role="alert">{error}</p>{/if}

			<button class="wide big" type="submit" disabled={busy} style="background: var({t.color})"><Icon name="check" /> Save</button>
			{#if entry}
				{#if confirmDelete}
					<div class="two">
						<button type="button" class="ghost" onclick={() => (confirmDelete = false)}>Keep it</button>
						<button type="button" class="danger" disabled={busy} onclick={remove}>Yes, delete</button>
					</div>
				{:else}
					<button type="button" class="danger wide" onclick={() => (confirmDelete = true)}><Icon name="trash" /> Delete entry</button>
				{/if}
			{/if}
		</form>
	{/if}
	{/if}
</Sheet>

<style>
	.seg {
		margin-bottom: 16px;
	}
	.timer {
		padding: 4px 0 8px;
	}
	.big {
		min-height: 64px;
		font-size: 1.1rem;
		border-radius: 20px;
	}
	.two {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}
	.times {
		display: grid;
		grid-template-columns: 1fr;
		gap: 12px;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin-inline: 0;
		min-width: 0;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 48px;
		font-weight: 700;
	}
	.food {
		display: flex;
		gap: 8px;
		margin-bottom: 8px;
	}
	.food .amt {
		width: 34%;
		flex: none;
	}
	.more {
		border: 1.5px solid var(--line);
		border-radius: var(--radius-s);
		padding: 0 14px;
	}
	.more summary {
		min-height: 48px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		list-style: none;
		font-weight: 700;
		cursor: pointer;
	}
	.more summary::-webkit-details-marker {
		display: none;
	}
	.more[open] summary :global(svg) {
		transform: rotate(180deg);
	}
	.more[open] {
		padding-bottom: 14px;
	}
	.advice p {
		margin: 0;
	}
	.dot {
		width: 14px;
		height: 14px;
		border-radius: 50%;
		display: inline-block;
		border: 1px solid rgba(0, 0, 0, 0.15);
	}
</style>
