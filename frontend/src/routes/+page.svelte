<script lang="ts">
	import { app, child, serverNow, units, wording } from '#lib/app.svelte.ts';
	import CrySheet from '#lib/CrySheet.svelte';
	import EntrySheet from '#lib/EntrySheet.svelte';
	import { fmtAgo, fmtDur, fmtTime, fmtUnit } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import NlBox from '#lib/NlBox.svelte';
	import TimerCard from '#lib/TimerCard.svelte';
	import Timeline from '#lib/Timeline.svelte';
	import { tick } from 'svelte';
	import { ACTIVITIES, trackers, type Entry, type EntryType } from '#lib/trackers.ts';

	let sheet = $state<{ type: EntryType; entry?: Entry } | null>(null);
	let cryHelp = $state(false);
	// --- cards: each one has a size and a place, set by the parent on this device (hold a card to change) ---
	type Size = 'small' | 'large' | 'wide';
	type Layout = { order: string[]; size: Record<string, Size> };
	const KEY = 'fb.home';
	const BIG = ['sleep', 'nursing', 'bottle', 'nappy'];
	const HINT: Record<string, string> = {
		sleep: 'Naps and night sleep, with a timer',
		nursing: 'Left and right side, with a timer',
		bottle: 'Formula or breast milk, and the amount',
		nappy: 'Wee, poo, colour and rash',
		solids: 'Foods and how the child liked them',
		potty: 'Potty visits and accidents',
		pump: 'Amount for each side, with a timer',
		growth: 'Weight, length and head size',
		temperature: 'Body temperature',
		medicine: 'Name and dose',
		activity: ACTIVITIES.map((a) => a[1]).join(', '),
		milestone: 'A first time or a new skill',
		note: 'All other things to remember',
		confined: 'Time in a car seat, pram, bouncer or swing',
		cry: 'Find out what to check first'
	};
	const all = $derived(trackers(wording()).map((t) => (t.type === 'cry' ? { ...t, label: 'Crying?' } : t)));

	function defaults(): Layout {
		const types = trackers('nappy').map((t) => t.type as string).filter((t) => t !== 'activity' && t !== 'cry');
		const order = [...types.slice(0, 4), 'activity', 'cry', ...types.slice(4)];
		return { order, size: Object.fromEntries(order.map((t) => [t, BIG.includes(t) ? 'large' : t === 'activity' || t === 'cry' ? 'wide' : 'small'])) };
	}
	function load(): Layout {
		const d = defaults();
		try {
			const saved = JSON.parse(localStorage.getItem(KEY) || 'null') as Layout | null;
			if (!saved) return d;
			// Keep only known cards, and add cards that a newer version brings.
			const order = saved.order.filter((t) => d.order.includes(t));
			return { order: [...order, ...d.order.filter((t) => !order.includes(t))], size: { ...d.size, ...saved.size } };
		} catch {
			return d;
		}
	}
	const layout = $state(load());
	function save() {
		try {
			localStorage.setItem(KEY, JSON.stringify(layout));
		} catch {
			/* this visit only */
		}
	}
	const cards = $derived(layout.order.map((type) => all.find((t) => t.type === type)!).filter(Boolean));

	let edit = $state(false);
	let selected = $state('');
	let dragging = $state('');
	let grid = $state<HTMLDivElement>();
	let hold: ReturnType<typeof setTimeout>;
	let from = { x: 0, y: 0 };
	let over = '';
	let skipClick = false;
	const picked = $derived(all.find((t) => t.type === selected));

	function tap(type: EntryType) {
		if (skipClick) return void (skipClick = false);
		if (edit) return void pick(type);
		if (type === 'cry') cryHelp = true;
		else sheet = { type };
	}
	/** Select a card in edit mode and show it above the edit bar. */
	function pick(type: string) {
		selected = type;
		tick().then(() => grid?.querySelector(`[data-card="${type}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
	}
	function down(e: PointerEvent, type: string) {
		from = { x: e.clientX, y: e.clientY };
		skipClick = false;
		const el = e.currentTarget as HTMLElement;
		const start = () => {
			edit = true;
			selected = dragging = type;
			over = '';
			el.setPointerCapture(e.pointerId);
		};
		if (edit) start();
		else
			hold = setTimeout(() => {
				skipClick = true; // the finger comes up on the card: that is not a tap
				navigator.vibrate?.(30);
				start();
			}, 500);
	}
	function move(e: PointerEvent) {
		if (!dragging) {
			if (Math.hypot(e.clientX - from.x, e.clientY - from.y) > 10) clearTimeout(hold); // a scroll, not a hold
			return;
		}
		if (Math.hypot(e.clientX - from.x, e.clientY - from.y) > 10) skipClick = true;
		// Near the top or the bottom of the screen: scroll, so a card can go to a place that is not on the screen.
		if (e.clientY < 90) scrollBy(0, -14);
		else if (e.clientY > innerHeight - 110) scrollBy(0, 14);
		// ponytail: the card jumps to the place under the finger (no card that follows the finger); add one if it feels wrong
		const target = (document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-card]') as HTMLElement | null)?.dataset.card ?? '';
		if (!target || target === dragging) return void (over = '');
		if (target === over) return; // after a move the finger is still on the other card: wait until it leaves
		over = target;
		place(dragging, layout.order.indexOf(target));
	}
	function up() {
		clearTimeout(hold);
		if (dragging) (save(), pick(dragging));
		dragging = '';
	}
	function place(type: string, to: number) {
		const at = layout.order.indexOf(type);
		if (to < 0 || to >= layout.order.length || at === to) return;
		layout.order.splice(at, 1);
		layout.order.splice(to, 0, type);
	}
	function shift(by: number) {
		place(selected, layout.order.indexOf(selected) + by);
		save();
	}
	function resize(size: Size) {
		layout.size[selected] = size;
		save();
		pick(selected);
	}
	function reset() {
		Object.assign(layout, defaults());
		save();
	}
	// Edit mode ends with a press on anything that is not a card or the edit bar.
	function outside(e: PointerEvent) {
		if (edit && !(e.target as HTMLElement).closest?.('[data-card], .editbar')) edit = false;
	}
	// While a card moves, the page must not scroll. (The browser decides to scroll at the first touch move.)
	$effect(() => {
		const stop = (e: TouchEvent) => dragging && e.cancelable && e.preventDefault();
		grid?.addEventListener('touchmove', stop, { passive: false });
		return () => grid?.removeEventListener('touchmove', stop);
	});
	const s = $derived(app.status);
	const timerOf = (type: string) => s?.timers.find((t) => t.type === type);

	function lastText(type: string) {
		if (timerOf(type)) return 'Running now';
		const e = s?.last[type];
		return e ? fmtAgo(e.ended_at ?? e.started_at, serverNow()) : 'Not yet';
	}
</script>

<svelte:head><title>Home · Frecklebubby</title></svelte:head>
<svelte:document onpointerdown={outside} />

{#if child()}
	{@const c = child()!}
	{#each s?.timers ?? [] as t (t.type + (t.data.kind ?? ''))}
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
	<div class="tiles" class:edit bind:this={grid} aria-describedby="tiles-help">
		{#each cards as t (t.type)}
			{@const size = layout.size[t.type]}
			<button class="tile {size}" class:sel={edit && selected === t.type} class:drag={dragging === t.type} data-card={t.type} style="--c: var({t.color})"
				aria-pressed={edit ? selected === t.type : undefined}
				onclick={() => tap(t.type)} onpointerdown={(e) => down(e, t.type)} onpointermove={move} onpointerup={up} onpointercancel={up}
				oncontextmenu={(e) => e.preventDefault()}>
				<Icon name={t.icon ?? t.type} size={size === 'small' ? 24 : 30} />
				{#if size === 'wide'}
					<span class="wide-text"><strong>{t.label}</strong><span>{HINT[t.type]}</span><span class="ago">{lastText(t.type)}</span></span>
				{:else}
					<strong>{t.label}</strong>
					{#if size === 'large'}<span>{lastText(t.type)}</span>{/if}
				{/if}
			</button>
		{/each}
	</div>
	<p id="tiles-help" class="sr-only">Hold a card to change its size or its place.</p>
	{#if edit}
		<div class="editbar card" role="toolbar" aria-label="Change the cards">
			<p class="small"><strong>{picked?.label ?? 'Select a card'}</strong> · Drag a card to move it.</p>
			<div class="seg" role="group" aria-label="Size">
				{#each [['small', 'Small'], ['large', 'Large'], ['wide', 'Wide']] as [v, l] (v)}
					<button aria-pressed={layout.size[selected] === v} disabled={!picked} onclick={() => resize(v as Size)}>{l}</button>
				{/each}
			</div>
			<div class="row">
				<button class="ghost small" disabled={!picked || layout.order[0] === selected} onclick={() => shift(-1)}>Move earlier</button>
				<button class="ghost small" disabled={!picked || layout.order.at(-1) === selected} onclick={() => shift(1)}>Move later</button>
				<button class="ghost small" onclick={reset}>Reset</button>
				<button class="small done" onclick={() => (edit = false)}>Done</button>
			</div>
		</div>
	{/if}

	{#if s}
		{@const d = s.today}
		<section class="card">
			<h2>Today</h2>
			<div class="totals">
				<div><span>Sleep</span><strong>{fmtDur(d.sleep.total_seconds)}</strong></div>
				<div><span>Breastfed</span><strong>{fmtDur(d.feeds.nursing_seconds)}</strong></div>
				<div><span>Wee</span><strong>{d.nappies.wet}</strong></div>
				<div><span>Poo</span><strong>{d.nappies.dirty}</strong></div>
				<div><span>Bottle</span><strong>{fmtUnit('volume', d.feeds.bottle_ml, units())}</strong></div>
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
		grid-template-columns: repeat(6, 1fr);
		gap: 10px;
		margin-bottom: 14px;
	}
	.tile {
		grid-column: span 2;
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
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}
	.tile.large {
		grid-column: span 3;
		min-height: 108px;
		padding: 14px 16px;
	}
	.tile strong {
		font-size: 0.95rem;
		margin-top: 4px;
	}
	.tile.large strong,
	.wide-text strong {
		font-size: 1.15rem;
	}
	.tile span {
		font-size: 0.85rem;
		font-weight: 600;
	}
	.tile.wide {
		grid-column: span 6;
		flex-direction: row;
		align-items: center;
		gap: 14px;
	}
	.tile.wide :global(svg) {
		flex: none;
	}
	.wide-text {
		display: flex;
		flex-direction: column;
	}
	.wide-text strong {
		margin: 0;
	}
	.wide-text .ago {
		opacity: 0.8;
	}
	/* edit mode: hold a card */
	.tiles.edit .tile {
		scroll-margin: 90px 0 250px; /* stay clear of the edit bar and the tab bar */
		outline: 2px dashed var(--muted);
		outline-offset: -2px;
		touch-action: none;
	}
	.tiles.edit .tile.sel {
		outline: 3px solid var(--accent);
	}
	.tile.drag {
		opacity: 0.7;
		transform: scale(1.04);
	}
	.editbar {
		position: sticky;
		bottom: calc(80px + env(safe-area-inset-bottom));
		z-index: 5;
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 10px;
		border: 2px solid var(--accent);
	}
	.editbar button {
		min-height: 40px;
		padding: 4px 12px;
	}
	.editbar p {
		margin: 0;
	}
	.editbar .row {
		flex-wrap: wrap;
	}
	.editbar .done {
		margin-left: auto;
	}
	/* Two rows: the two times (sleep, breastfed) are wide and get half a row each; the three counts share the second row. */
	.totals {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: 8px;
		margin-bottom: 8px;
	}
	.totals div {
		background: var(--cloud);
		border-radius: 16px;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		grid-column: span 2;
		min-width: 0;
	}
	.totals div:nth-child(-n + 2) {
		grid-column: span 3;
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
