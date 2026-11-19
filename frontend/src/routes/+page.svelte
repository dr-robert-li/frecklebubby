<script lang="ts">
	import { app, child, serverNow, units, wording } from '#lib/app.svelte.ts';
	import CrySheet from '#lib/CrySheet.svelte';
	import EntrySheet from '#lib/EntrySheet.svelte';
	import { fmtAgo, fmtDur, fmtTime, fmtUnit } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import NlBox from '#lib/NlBox.svelte';
	import TimerCard from '#lib/TimerCard.svelte';
	import Timeline from '#lib/Timeline.svelte';
	import { trackers, type Entry, type EntryType } from '#lib/trackers.ts';

	let sheet = $state<{ type: EntryType; entry?: Entry } | null>(null);
	let cryHelp = $state(false);
	const list = $derived(trackers(wording()).filter((t) => t.type !== 'cry'));
	const s = $derived(app.status);
	const timerOf = (type: string) => s?.timers.find((t) => t.type === type);

	function lastText(type: string) {
		if (timerOf(type)) return 'Running now';
		const e = s?.last[type];
		return e ? fmtAgo(e.ended_at ?? e.started_at, serverNow()) : 'Not yet';
	}
</script>

<svelte:head><title>Home · Frecklebubby</title></svelte:head>

{#if child()}
	{@const c = child()!}
	{#each s?.timers ?? [] as t (t.type)}
		<TimerCard timer={t} childId={c.id} />
	{/each}

	{#if s?.prediction}
		{@const p = s.prediction}
		{@const late = Date.parse(p.start) < serverNow()}
		<section class="card next">
			<Icon name="sleep" />
			<div>
				<h2>{p.kind === 'bedtime' ? 'Bedtime' : 'Next nap'} {late ? 'is due now' : `from ${fmtTime(p.start)}`}</h2>
				<p class="muted small">Window {fmtTime(p.start)}–{fmtTime(p.end)}. {p.note}</p>
			</div>
		</section>
	{/if}

	<NlBox childId={c.id} />

	<h2 class="sr-only">Log</h2>
	<div class="tiles big">
		{#each list.slice(0, 4) as t (t.type)}
			<button class="tile" style="--c: var({t.color})" onclick={() => (sheet = { type: t.type })}>
				<Icon name={t.type} size={30} />
				<strong>{t.label}</strong>
				<span>{lastText(t.type)}</span>
			</button>
		{/each}
	</div>
	<button class="tile cry" style="--c: var(--coral)" onclick={() => (cryHelp = true)}>
		<Icon name="cry" size={30} />
		<span class="cry-text"><strong>Crying?</strong><span>Find out what to check first</span></span>
	</button>
	<div class="tiles">
		{#each list.slice(4) as t (t.type)}
			<button class="tile" style="--c: var({t.color})" onclick={() => (sheet = { type: t.type })}>
				<Icon name={t.type} />
				<strong>{t.label}</strong>
			</button>
		{/each}
	</div>

	{#if s}
		{@const d = s.today}
		<section class="card">
			<h2>Today</h2>
			<div class="totals">
				<div><span>Sleep</span><strong>{fmtDur(d.sleep.total_seconds)}</strong></div>
				<div><span>Feeds</span><strong>{d.feeds.count}</strong></div>
				<div><span>Wet</span><strong>{d.nappies.wet}</strong></div>
				<div><span>Dirty</span><strong>{d.nappies.dirty}</strong></div>
				{#if d.feeds.bottle_ml}<div><span>Bottle</span><strong>{fmtUnit('volume', d.feeds.bottle_ml, units())}</strong></div>{/if}
			</div>
			<Timeline entries={app.today} onpick={(e) => (sheet = { type: e.type, entry: e })} empty="Nothing logged today. Tap a tile above to start." />
		</section>
	{/if}

	{#if sheet}
		<EntrySheet type={sheet.type} entry={sheet.entry} childId={c.id} onclose={() => (sheet = null)} />
	{/if}
	{#if cryHelp}
		<CrySheet childId={c.id} onclose={() => (cryHelp = false)} onmanual={() => ((cryHelp = false), (sheet = { type: 'cry' }))} />
	{/if}
{/if}

<style>
	.next {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		background: var(--lavender);
		color: var(--ink-strong);
	}
	.next h2 {
		margin: 0 0 2px;
	}
	.next .muted {
		color: var(--ink-strong);
		margin: 0;
	}
	.tiles {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
		margin-bottom: 14px;
	}
	.tiles.big {
		grid-template-columns: repeat(2, 1fr);
	}
	.tile {
		background: var(--c);
		color: var(--ink-strong);
		border-radius: 22px;
		flex-direction: column;
		align-items: flex-start;
		justify-content: flex-start;
		gap: 2px;
		padding: 12px 14px;
		min-height: 76px;
		text-align: left;
		box-shadow: var(--shadow);
	}
	.big .tile {
		min-height: 108px;
		padding: 14px 16px;
	}
	.tile strong {
		font-size: 1rem;
		margin-top: 4px;
	}
	.big .tile strong {
		font-size: 1.15rem;
	}
	.tile span {
		font-size: 0.85rem;
		font-weight: 600;
	}
	.tile.cry {
		width: 100%;
		flex-direction: row;
		align-items: center;
		gap: 14px;
		min-height: 76px;
		margin-bottom: 14px;
	}
	.cry-text {
		display: flex;
		flex-direction: column;
	}
	.cry-text strong {
		font-size: 1.15rem;
		margin: 0;
	}
	.totals {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(70px, 1fr));
		gap: 8px;
		margin-bottom: 8px;
	}
	.totals div {
		background: var(--cloud);
		border-radius: 16px;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
	}
	.totals span {
		font-size: 0.8rem;
		color: var(--muted);
		font-weight: 700;
	}
	.totals strong {
		color: var(--ink-strong);
		font-size: 1.05rem;
		white-space: nowrap;
	}
</style>
