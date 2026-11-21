<script lang="ts">
	import { api } from '#lib/api.ts';
	import { child, wording } from '#lib/app.svelte.ts';
	import EntrySheet from '#lib/EntrySheet.svelte';
	import { units } from '#lib/app.svelte.ts';
	import { addDays, fmtDay, fmtDayLabel, fmtDur, fmtUnit, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import Pattern from '#lib/Pattern.svelte';
	import Timeline from '#lib/Timeline.svelte';
	import { trackers, type Entry } from '#lib/trackers.ts';

	const VIEWS = [['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['list', 'List']] as const;
	let view = $state<(typeof VIEWS)[number][0]>('day');
	// Week and Month: the 7 or 30 days that end on the selected day
	const span = $derived(view === 'week' ? 7 : view === 'month' ? 30 : 1);
	const days = $derived(Array.from({ length: span }, (_, i) => addDays(day, i + 1 - span)));
	let day = $state(localDay());
	// types: the selected entry types. All are selected at the start.
	const all = $derived(trackers(wording()));
	let off = $state<string[]>([]);
	const types = $derived(all.filter((t) => !off.includes(t.type)));
	const SORTS: [string, string][] = [
		['time', 'Time'], ['duration', 'Duration'], ['volume', 'Volume'], ['weight', 'Weight'],
		['height', 'Length or height'], ['head', 'Head'], ['temperature', 'Temperature']
	];
	// List: the days with a check mark. With none, the list shows all days.
	const recent = $derived(Array.from({ length: 30 }, (_, i) => addDays(localDay(), -i)));
	let picked = $state<string[]>([]);
	let sort = $state('time');
	let dir = $state<'desc' | 'asc'>('desc');
	let entries = $state<Entry[]>([]);
	let more = $state(false);
	let loading = $state(true);
	let error = $state('');
	let edit = $state<Entry | null>(null);
	let version = $state(0);

	async function load(append = false) {
		const c = child();
		if (!c) return;
		if (!types.length) return void ((entries = []), (more = false), (loading = false));
		loading = true;
		error = '';
		const q = new URLSearchParams();
		if (off.length) for (const t of types) q.append('type', t.type);
		if (view !== 'list') {
			// a day reads from the morning to the evening. Week and Month start one day before, for a sleep that
			// goes past midnight into the first day.
			q.set('from', `${addDays(day, span === 1 ? 0 : -span)}T00:00`);
			q.set('to', `${addDays(day, 1)}T00:00`);
			q.set('limit', '1000');
			q.set('dir', 'asc');
		} else {
			q.set('limit', picked.length ? '1000' : '50');
			q.set('sort', sort);
			q.set('dir', dir);
			if (append) q.set('offset', String(entries.length));
			if (picked.length) {
				q.set('from', `${[...picked].sort()[0]}T00:00`);
				q.set('to', `${addDays([...picked].sort().at(-1)!, 1)}T00:00`);
			}
		}
		try {
			let page = await api<Entry[]>(`/children/${c.id}/entries?${q}`);
			if (view !== 'list' || picked.length) {
				// a month of a newborn can have more than 1000 entries: read all pages
				const all = [...page];
				while (page.length === 1000) {
					q.set('offset', String(all.length));
					page = await api<Entry[]>(`/children/${c.id}/entries?${q}`);
					all.push(...page);
				}
				page = view === 'list' ? all.filter((e) => picked.includes(localDay(e.started_at))) : all;
			}
			entries = append ? [...entries, ...page] : page;
			more = view === 'list' && !picked.length && page.length === 50;
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void [view, day, off, picked, sort, dir, version, child()];
		load();
	});

	// the total of the selected days, for the amounts that you can add
	const total = $derived.by(() => {
		if (sort === 'volume')
			return fmtUnit('volume', entries.reduce((s, e) => s + (e.data.amount_ml ?? e.data.total_ml ?? (e.data.left_ml ?? 0) + (e.data.right_ml ?? 0)), 0), units());
		if (sort === 'duration')
			return fmtDur(entries.reduce((s, e) => s + (e.ended_at ? (Date.parse(e.ended_at) - Date.parse(e.started_at)) / 1000 : (e.data.left_seconds ?? 0) + (e.data.right_seconds ?? 0)), 0));
		return '';
	});
</script>

<svelte:head><title>History · Frecklebubby</title></svelte:head>

<h1>History</h1>
<div class="seg" role="group" aria-label="View">
	{#each VIEWS as [k, l] (k)}<button aria-pressed={view === k} onclick={() => ((entries = []), (view = k))}>{l}</button>{/each}
</div>

<details class="filters card">
	<summary>Types: {off.length ? `${types.length} of ${all.length}` : 'all'}</summary>
	<div class="row">
		<button class="ghost" disabled={!off.length} onclick={() => (off = [])}>Select all</button>
		<button class="ghost" disabled={!types.length} onclick={() => (off = all.map((t) => t.type))}>Deselect all</button>
	</div>
	<div class="types">
		{#each all as t (t.type)}
			<label class="pick"><input type="checkbox" checked={!off.includes(t.type)}
				onchange={() => (off = off.includes(t.type) ? off.filter((x) => x !== t.type) : [...off, t.type])} /> {t.label}</label>
		{/each}
	</div>
</details>

{#if view === 'list'}
	<details class="filters card">
		<summary>Days: {picked.length ? `${picked.length} selected` : 'all'}</summary>
		<p class="muted small">Select days to show only these days together. With no day selected, the list shows all days.</p>
		<div class="row">
			<button class="ghost" disabled={picked.length === recent.length} onclick={() => (picked = [...recent])}>Select all</button>
			<button class="ghost" disabled={!picked.length} onclick={() => (picked = [])}>Deselect all</button>
		</div>
		<div class="types">
			{#each recent as d (d)}
				<label class="pick"><input type="checkbox" checked={picked.includes(d)}
					onchange={() => (picked = picked.includes(d) ? picked.filter((x) => x !== d) : [...picked, d])} /> {d >= addDays(localDay(), -1) ? fmtDayLabel(d) : fmtDay(d, { weekday: 'short', day: 'numeric', month: 'short' })}</label>
			{/each}
		</div>
	</details>
	<div class="order">
		<label class="field"><span>Order by</span>
			<select bind:value={sort}>
				{#each SORTS as [k, l] (k)}<option value={k}>{l}</option>{/each}
			</select>
		</label>
		<div class="seg" role="group" aria-label="Direction">
			<button aria-pressed={dir === 'desc'} onclick={() => (dir = 'desc')}>{sort === 'time' ? 'Newest first' : 'Largest first'}</button>
			<button aria-pressed={dir === 'asc'} onclick={() => (dir = 'asc')}>{sort === 'time' ? 'Oldest first' : 'Smallest first'}</button>
		</div>
	</div>
	{#if sort !== 'time'}<p class="muted small">The list shows only the entries that have this amount.</p>{/if}
{/if}

{#if view !== 'list'}
	<div class="spread daynav">
		<button class="icon" aria-label={span === 1 ? 'Day before' : `${span} days before`} onclick={() => (day = addDays(day, -span))}><Icon name="left" /></button>
		<label class="daypick"><span class="sr-only">{span === 1 ? 'Day' : 'Last day'}</span>
			<strong>{span === 1 ? fmtDayLabel(day) : `${fmtDay(days[0], { day: 'numeric', month: 'short' })} to ${fmtDay(day, { day: 'numeric', month: 'short' })}`}</strong>
			<input type="date" bind:value={day} max={localDay()} aria-label="Choose a day" />
		</label>
		<button class="icon" aria-label={span === 1 ? 'Next day' : `${span} days after`} disabled={day >= localDay()} onclick={() => (day = addDays(day, span) > localDay() ? localDay() : addDays(day, span))}><Icon name="right" /></button>
	</div>
{/if}

{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="card">
	{#if view === 'day'}
		<Timeline {entries} onpick={(e) => (edit = e)} empty={loading ? 'Loading…' : types.length ? 'Nothing logged on this day.' : 'Select one type or more.'} />
	{:else if view !== 'list'}
		{#if !types.length}
			<p class="empty">Select one type or more.</p>
		{:else}
			<Pattern {days} {entries} tall={view === 'week'} onpick={(d) => ((entries = []), (day = d), (view = 'day'))} />
		{/if}
	{:else}
		{#if !types.length}
			<p class="empty">Select one type or more.</p>
		{:else}
			{#if picked.length && entries.length}
				<p class="muted small sum" role="status">{entries.length} {entries.length === 1 ? 'entry' : 'entries'} on {picked.length} {picked.length === 1 ? 'day' : 'days'}{total ? `. Total: ${total}` : ''}</p>
			{/if}
			<Timeline {entries} dated onpick={(e) => (edit = e)} empty={loading ? 'Loading…' : sort === 'time' ? (picked.length ? 'Nothing logged on these days.' : 'Nothing logged yet.') : 'No entry has this amount.'} />
		{/if}
		{#if more}<button class="ghost wide" disabled={loading} onclick={() => load(true)}>Show older</button>{/if}
	{/if}
</section>

{#if edit && child()}
	<EntrySheet type={edit.type} entry={edit} childId={child()!.id} onclose={() => ((edit = null), version++)} />
{/if}

<style>
	.seg {
		margin-bottom: 10px;
	}
	.filters {
		margin-bottom: 10px;
		padding: 10px 14px;
	}
	.filters summary {
		font-weight: 700;
		line-height: 36px;
		cursor: pointer;
	}
	.row {
		display: flex;
		gap: 8px;
		margin: 8px 0;
	}
	.types {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
	}
	.pick {
		display: flex;
		gap: 10px;
		align-items: center;
		padding: 6px 0;
	}
	.order {
		display: grid;
		gap: 8px;
		margin-bottom: 10px;
	}
	.daynav {
		margin-bottom: 10px;
	}
	.daypick {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		font-size: 1.05rem;
	}
	.daypick input {
		max-width: 170px;
		min-height: 40px;
		padding: 4px 10px;
		margin-top: 4px;
	}
	.sum {
		margin: 0 0 6px;
	}
</style>
