<script lang="ts" module>
	/** The average of a day. Days before the first day with a value do not count: there were no logs then. */
	export function average(values: number[]): number {
		const first = values.findIndex((v) => v > 0);
		const used = first < 0 ? [] : values.slice(first);
		return used.length ? used.reduce((a, v) => a + v, 0) / used.length : 0;
	}
</script>

<script lang="ts">
	// Stacked bars per day, with a dotted line at the average. Native <title> tooltips per day; a hidden table for screen readers.
	type Series = { label: string; color: string; values: number[] };
	let {
		title,
		labels,
		series,
		fmt = (v: number) => String(v),
		band = null,
		line = null,
		counts = false
	}: {
		title: string; labels: string[]; series: Series[]; fmt?: (v: number) => string; band?: [number, number] | null;
		line?: { value: number; label: string } | null; counts?: boolean;
	} = $props();

	const W = 340, H = 170, L = 34, B = 22, T = 8;
	const totals = $derived(labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0)));
	const max = $derived(niceMax(Math.max(1, ...totals, band?.[1] ?? 0, line?.value ?? 0)));
	const avg = $derived(average(totals));
	// with many days there is no room for each label: show each 5th
	const every = $derived(labels.length > 10 ? 5 : 1);
	const y = (v: number) => H - B - (v / max) * (H - B - T);
	const step = $derived((W - L) / labels.length);
	const bw = $derived(Math.min(28, step * 0.55));

	function niceMax(v: number) {
		if (counts) return Math.max(2, Math.ceil(v / 2) * 2); // whole-number ticks: 0, half, max
		const p = 10 ** Math.floor(Math.log10(v));
		return ([1, 2, 2.5, 5, 10].find((m) => m * p >= v) ?? 10) * p;
	}
	function segs(i: number) {
		let base = 0;
		return series.map((s) => {
			const v = s.values[i] || 0;
			const r = { s, v, y0: y(base), y1: y(base + v) };
			base += v;
			return r;
		});
	}
</script>

<figure>
	<figcaption class="spread">
		<h3>{title}</h3>
		{#if series.length > 1 || line || avg}
			<span class="legend">
				{#if series.length > 1}{#each series as s (s.label)}<span><i style="background:{s.color}"></i>{s.label}</span>{/each}{/if}
				{#if line}<span><i class="dash"></i>{line.label}</span>{/if}
				{#if avg}<span><i class="dash dot"></i>Average {fmt(Math.round(avg * 10) / 10)}</span>{/if}
			</span>
		{/if}
	</figcaption>
	<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title} chart. Values are in the table below.">
		{#if band}
			<rect x={L} width={W - L} y={y(band[1])} height={y(band[0]) - y(band[1])} class="band" />
			<text x={W - 4} y={y(band[1]) - 3} class="tick" text-anchor="end">Common range</text>
		{/if}
		{#if line}
			<line x1={L} x2={W} y1={y(line.value)} y2={y(line.value)} class="target" />
		{/if}
		{#each [0, 0.5, 1] as f (f)}
			<line x1={L} x2={W} y1={y(max * f)} y2={y(max * f)} class="grid" />
			<text x={L - 6} y={y(max * f) + 4} class="tick" text-anchor="end">{fmt(max * f)}</text>
		{/each}
		{#each labels as lab, i (i)}
			{@const cx = L + step * i + step / 2}
			<g>
				<title>{lab}: {series.map((s) => `${s.label} ${fmt(s.values[i] || 0)}`).join(', ')}</title>
				<rect x={cx - step / 2} y={T} width={step} height={H - B - T} fill="transparent" />
				{#each segs(i) as seg (seg.s.label)}
					{#if seg.v > 0}
						<rect x={cx - bw / 2} y={seg.y1} width={bw} height={Math.max(0, seg.y0 - seg.y1 - 2)} rx="4" fill={seg.s.color} />
					{/if}
				{/each}
				{#if (labels.length - 1 - i) % every === 0}<text x={cx} y={H - 6} class="tick" text-anchor="middle">{lab}</text>{/if}
			</g>
		{/each}
		{#if avg}<line x1={L} x2={W} y1={y(avg)} y2={y(avg)} class="avg" />{/if}
	</svg>
	<table class="sr-only">
		<caption>{title}</caption>
		<thead><tr><th>Day</th>{#each series as s (s.label)}<th>{s.label}</th>{/each}</tr></thead>
		<tbody>
			{#each labels as lab, i (i)}
				<tr><td>{lab}</td>{#each series as s (s.label)}<td>{fmt(s.values[i] || 0)}</td>{/each}</tr>
			{/each}
		</tbody>
		{#if avg}<tfoot><tr><td>Average</td><td colspan={series.length}>{fmt(Math.round(avg * 10) / 10)}</td></tr></tfoot>{/if}
	</table>
</figure>

<style>
	figure {
		margin: 0 0 8px;
	}
	figcaption {
		margin-bottom: 4px;
		flex-wrap: wrap;
	}
	h3 {
		margin: 0;
	}
	svg {
		width: 100%;
		height: auto;
		display: block;
		overflow: visible;
	}
	.grid {
		stroke: var(--line);
		stroke-width: 1;
	}
	.target {
		stroke: var(--ink);
		stroke-width: 1.5;
		stroke-dasharray: 5 4;
	}
	.avg {
		stroke: var(--ink-strong);
		stroke-width: 2;
		stroke-dasharray: 0.1 5;
		stroke-linecap: round;
		pointer-events: none;
	}
	.band {
		fill: var(--mint);
		opacity: 0.45;
	}
	.tick {
		font-size: 10px;
		fill: var(--muted);
		font-weight: 600;
	}
	.legend .dash {
		height: 0;
		border-radius: 0;
		border-top: 2px dashed var(--ink);
	}
	.legend .dot {
		border-top-style: dotted;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		font-size: 0.85rem;
		font-weight: 700;
	}
	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.legend i {
		width: 12px;
		height: 12px;
		border-radius: 4px;
		display: inline-block;
	}
</style>
