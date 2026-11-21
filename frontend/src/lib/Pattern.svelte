<script lang="ts">
	// Week and Month in History: one row for each day, with the 24 hours from left to right. Sleep is a bar,
	// each other entry is a mark at its time. A row opens its day. The Week has tall rows with one lane for
	// each group; the Month has thin rows with all marks on the sleep bars.
	import { wording } from './app.svelte';
	import { addDays, fmtDay, fmtDur, localDay, prefs, toLocalInput } from './format.svelte';
	import { tracker, type Entry } from './trackers';

	let { days, entries, tall, onpick }: { days: string[]; entries: Entry[]; tall: boolean; onpick: (day: string) => void } = $props();

	const LANES: [string, string, string[]][] = [
		['sleep', 'Sleep', ['sleep']],
		['feed', 'Feeds', ['nursing', 'bottle', 'solids', 'pump']],
		['nappy', wording() === 'diaper' ? 'Diapers' : 'Nappies', ['nappy', 'potty']],
		['other', 'Other', []]
	];
	// One clear colour for each type. The tracker colours are pale and some types share one, so the marks get
	// their own hue (the angle of the oklch colour). Sleep keeps its lavender.
	const HUE: Record<string, number> = {
		sleep: 295, nursing: 350, bottle: 245, solids: 75, pump: 320, nappy: 150, potty: 195, medicine: 25,
		temperature: 50, growth: 125, activity: 100, confined: 215, milestone: 280, note: 265, cry: 10
	};
	const laneOf = (type: string) => LANES.find((l) => l[2].includes(type))?.[0] ?? 'other';
	const min = (local: string) => Number(local.slice(11, 13)) * 60 + Number(local.slice(14, 16));

	type Mark = { id: string; type: string; lane: string; from: number; to: number };
	// the parts of each entry in each day: an entry that goes past midnight has a part in each day
	const rows = $derived.by(() => {
		const by = new Map<string, { marks: Mark[]; sleep: number; n: Record<string, number> }>(
			days.map((d) => [d, { marks: [], sleep: 0, n: {} }])
		);
		for (const e of entries) {
			const a = toLocalInput(e.started_at);
			const b = e.ended_at ? toLocalInput(e.ended_at) : a;
			const lane = laneOf(e.type);
			const first = by.get(a.slice(0, 10));
			if (first) first.n[lane] = (first.n[lane] ?? 0) + 1;
			for (let d = a.slice(0, 10); d <= b.slice(0, 10); d = addDays(d, 1)) {
				const row = by.get(d);
				const from = d === a.slice(0, 10) ? min(a) : 0;
				const to = d === b.slice(0, 10) ? min(b) : 1440;
				if (!row) continue;
				row.marks.push({ id: `${e.id}-${d}`, type: e.type, lane, from, to });
				if (e.type === 'sleep') row.sleep += to - from;
			}
		}
		return days.map((d) => ({ day: d, ...by.get(d)! }));
	});
	const lanes = $derived(LANES.filter((l) => rows.some((r) => r.marks.some((m) => m.lane === l[0]))));
	const types = $derived([...new Set(rows.flatMap((r) => r.marks.map((m) => m.type)))].map((t) => tracker(t, wording())));
	const hours = $derived((prefs.clock24 ? ['00', '06', '12', '18'] : ['12 am', '6 am', '12 pm', '6 pm']));

	function totals(r: (typeof rows)[number], short = false): string {
		const p: string[] = [];
		if (r.sleep) p.push(short ? `${(r.sleep / 60).toFixed(1)} h` : `Sleep ${fmtDur(r.sleep * 60)}`);
		if (short) return p[0] ?? (r.marks.length ? String(r.marks.length) : '');
		for (const [k, label] of LANES.slice(1)) if (r.n[k]) p.push(`${label} ${r.n[k]}`);
		return p.join(' · ') || 'Nothing logged';
	}
	const style = (m: Mark) => `left:${(m.from / 14.4).toFixed(2)}%;width:${((m.to - m.from) / 14.4).toFixed(2)}%;--h:${HUE[m.type] ?? 0}`;
</script>

<div class="pattern" class:tall>
	<p class="muted small about">{tall ? `Each day has one lane for each group, from the top: ${lanes.map((l) => l[1].toLowerCase()).join(', ')}. ` : 'The number at the end of a row is the hours of sleep. '}Select a day to open it.</p>
	<p class="legend small" aria-label="Key">
		{#each types as t (t.type)}<span><i class={t.type === 'sleep' ? 'bar' : 'mark'} style="--h:{HUE[t.type] ?? 0}"></i>{t.label}</span>{/each}
	</p>
	<div class="axis" aria-hidden="true">
		<span class="label"></span>
		<span class="track">{#each hours as h, i (h)}<span style="left:{i * 25}%">{h}</span>{/each}</span>
		{#if !tall}<span class="sum"></span>{/if}
	</div>
	<ul aria-label={tall ? 'Week' : 'Month'}>
		{#each rows as r (r.day)}
			<li>
				<button class="day" class:today={r.day === localDay()} onclick={() => onpick(r.day)} aria-label="Open {fmtDay(r.day)}: {totals(r)}">
					<span class="label">{fmtDay(r.day, { weekday: 'short' })} <strong>{Number(r.day.slice(8))}</strong></span>
					<span class="track">
						{#if tall}
							{#each lanes as [k] (k)}
								<span class="lane">{#each r.marks.filter((m) => m.lane === k) as m (m.id)}<i class={m.type === 'sleep' ? 'bar' : 'mark'} style={style(m)}></i>{/each}</span>
							{/each}
						{:else}
							<span class="lane">{#each r.marks as m (m.id)}<i class={m.type === 'sleep' ? 'bar' : 'mark'} style={style(m)}></i>{/each}</span>
						{/if}
					</span>
					{#if !tall}<span class="sum">{totals(r, true)}</span>{/if}
				</button>
				{#if tall}<p class="totals muted small">{totals(r)}</p>{/if}
			</li>
		{/each}
	</ul>
</div>

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.axis,
	.day {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
	}
	.day {
		background: transparent;
		padding: 2px 0;
		min-height: 0;
		border-radius: 8px;
		font-weight: 400;
		color: var(--ink);
	}
	.day:hover {
		background: var(--cloud);
	}
	.label {
		width: 52px;
		flex: none;
		text-align: left;
		font-size: 0.8rem;
		color: var(--muted);
	}
	.label strong {
		color: var(--ink-strong);
	}
	.today .label strong {
		text-decoration: underline;
	}
	.sum {
		width: 44px;
		flex: none;
		text-align: right;
		font-size: 0.8rem;
		font-variant-numeric: tabular-nums;
	}
	.track {
		position: relative;
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.axis .track {
		height: 18px;
		font-size: 0.72rem;
		color: var(--muted);
	}
	.axis .track span {
		position: absolute;
		padding-left: 3px;
		border-left: 1px solid var(--line);
		white-space: nowrap;
	}
	.lane {
		position: relative;
		display: block;
		height: 16px;
		border-radius: 4px;
		/* a line at each 6 hours */
		background: linear-gradient(to right, var(--line) 1px, transparent 1px) 0 0 / 25% 100%, var(--cloud);
		overflow: hidden;
	}
	.tall .lane {
		height: 14px;
	}
	i {
		position: absolute;
		top: 0;
		bottom: 0;
	}
	.bar {
		background: oklch(0.66 0.11 calc(var(--h) * 1deg));
		min-width: 2px;
		border-radius: 2px;
	}
	.mark {
		background: oklch(0.58 0.17 calc(var(--h) * 1deg));
		min-width: 3px;
		border-radius: 1px;
	}
	.pattern:not(.tall) .mark {
		top: 45%;
	}
	.about {
		margin: 0 0 10px;
	}
	.totals {
		margin: 0 0 8px 60px;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
		margin: 0 0 10px;
	}
	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.legend i {
		position: static;
		display: inline-block;
		height: 14px;
		width: 14px;
	}
	.legend i.mark {
		width: 4px;
	}
</style>
