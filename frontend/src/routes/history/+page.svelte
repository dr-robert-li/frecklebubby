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
	let type = $state('');
	let entries = $state<Entry[]>([]);
	let more = $state(false);
	let loading = $state(true);
	let error = $state('');
	let edit = $state<Entry | null>(null);
	let version = $state(0);

	async function load(append = false) {
		const c = child();
		if (!c) return;
		loading = true;
		error = '';
		const q = new URLSearchParams();
		if (type) q.set('type', type);
		if (view === 'day') {
			q.set('from', `${day}T00:00`);
			q.set('to', `${addDays(day, 1)}T00:00`);
			q.set('limit', '500');
		} else {
			q.set('limit', '50');
			if (append && entries.length) q.set('before', entries.at(-1)!.started_at);
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
		void [view, day, type, version, child()];
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

<div class="filters">
	<label class="sr-only" for="type-filter">Show</label>
	<select id="type-filter" bind:value={type}>
		<option value="">All types</option>
		{#each trackers(wording()) as t (t.type)}<option value={t.type}>{t.label}</option>{/each}
	</select>
</div>

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
		<Timeline {entries} onpick={(e) => (edit = e)} empty={loading ? 'Loading…' : 'Nothing logged on this day.'} />
	{:else}
		{#each groups as [d, list] (d)}
			<h2 class="dayhead">{fmtDayLabel(d)}</h2>
			<Timeline entries={list} onpick={(e) => (edit = e)} />
		{:else}
			<p class="empty">{loading ? 'Loading…' : 'Nothing logged yet.'}</p>
		{/each}
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
