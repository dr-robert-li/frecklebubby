<script lang="ts">
	import { api } from '#lib/api.ts';
	import { child, wording } from '#lib/app.svelte.ts';
	import EntrySheet from '#lib/EntrySheet.svelte';
	import { addDays, fmtDayLabel, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import Timeline from '#lib/Timeline.svelte';
	import { trackers, type Entry } from '#lib/trackers.ts';

	let view = $state<'day' | 'list'>('day');
	let day = $state(localDay());
	// types: the selected entry types. All are selected at the start.
	const all = $derived(trackers(wording()));
	let off = $state<string[]>([]);
	const types = $derived(all.filter((t) => !off.includes(t.type)));
	const SORTS: [string, string][] = [
		['time', 'Time'], ['duration', 'Duration'], ['volume', 'Volume'], ['weight', 'Weight'],
		['height', 'Length or height'], ['head', 'Head'], ['temperature', 'Temperature']
	];
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
		if (view === 'day') {
			// a day reads from the morning to the evening
			q.set('from', `${day}T00:00`);
			q.set('to', `${addDays(day, 1)}T00:00`);
			q.set('limit', '500');
			q.set('dir', 'asc');
		} else {
			q.set('limit', '50');
			q.set('sort', sort);
			q.set('dir', dir);
			if (append) q.set('offset', String(entries.length));
		}
		try {
			const page = await api<Entry[]>(`/children/${c.id}/entries?${q}`);
			entries = append ? [...entries, ...page] : page;
			more = view === 'list' && page.length === 50;
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void [view, day, off, sort, dir, version, child()];
		load();
	});

	// group the list view by local day
	const groups = $derived.by(() => {
		const g: [string, Entry[]][] = [];
		for (const e of entries) {
			const d = localDay(e.started_at);
			if (g.at(-1)?.[0] !== d) g.push([d, []]);
			g.at(-1)![1].push(e);
		}
		return g;
	});
</script>

<svelte:head><title>History · Frecklebubby</title></svelte:head>

<h1>History</h1>
<div class="seg" role="group" aria-label="View">
	<button aria-pressed={view === 'day'} onclick={() => (view = 'day')}>Day</button>
	<button aria-pressed={view === 'list'} onclick={() => (view = 'list')}>List</button>
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

{#if view === 'day'}
	<div class="spread daynav">
		<button class="icon" aria-label="Day before" onclick={() => (day = addDays(day, -1))}><Icon name="left" /></button>
		<label class="daypick"><span class="sr-only">Day</span>
			<strong>{fmtDayLabel(day)}</strong>
			<input type="date" bind:value={day} max={localDay()} aria-label="Choose a day" />
		</label>
		<button class="icon" aria-label="Next day" disabled={day >= localDay()} onclick={() => (day = addDays(day, 1))}><Icon name="right" /></button>
	</div>
{/if}

{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="card">
	{#if view === 'day'}
		<Timeline {entries} onpick={(e) => (edit = e)} empty={loading ? 'Loading…' : types.length ? 'Nothing logged on this day.' : 'Select one type or more.'} />
	{:else}
		{#if !types.length}
			<p class="empty">Select one type or more.</p>
		{:else if sort !== 'time'}
			<Timeline {entries} dated onpick={(e) => (edit = e)} empty={loading ? 'Loading…' : 'No entry has this amount.'} />
		{:else}
		{#each groups as [d, list] (d)}
			<h2 class="dayhead">{fmtDayLabel(d)}</h2>
			<Timeline entries={list} onpick={(e) => (edit = e)} />
		{:else}
			<p class="empty">{loading ? 'Loading…' : 'Nothing logged yet.'}</p>
		{/each}
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
		min-height: 32px;
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
	.dayhead {
		font-size: 1rem;
		margin: 12px 0 4px;
		color: var(--muted);
	}
	.dayhead:first-child {
		margin-top: 0;
	}
</style>
