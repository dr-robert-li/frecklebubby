<script lang="ts">
	// Stacked bars per day. Native <title> tooltips per day; a hidden table for screen readers.
	type Series = { label: string; color: string; values: number[] };
	let {
		title,
		labels,
		series,
		fmt = (v: number) => String(v),
		band = null,
		counts = false
	}: { title: string; labels: string[]; series: Series[]; fmt?: (v: number) => string; band?: [number, number] | null; counts?: boolean } = $props();

	const W = 340, H = 170, L = 34, B = 22, T = 8;
	const totals = $derived(labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0)));
	const max = $derived(niceMax(Math.max(1, ...totals, band?.[1] ?? 0)));
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
		{#if series.length > 1}
			<span class="legend">
				{#each series as s (s.label)}<span><i style="background:{s.color}"></i>{s.label}</span>{/each}
			</span>
		{/if}
	</figcaption>
	<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title} chart. Values are in the table below.">
		{#if band}
			<rect x={L} width={W - L} y={y(band[1])} height={y(band[0]) - y(band[1])} class="band" />
			<text x={W - 4} y={y(band[1]) - 3} class="tick" text-anchor="end">Common range</text>
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
				<text x={cx} y={H - 6} class="tick" text-anchor="middle">{lab}</text>
			</g>
		{/each}
	</svg>
	<table class="sr-only">
		<caption>{title}</caption>
		<thead><tr><th>Day</th>{#each series as s (s.label)}<th>{s.label}</th>{/each}</tr></thead>
		<tbody>
			{#each labels as lab, i (i)}
				<tr><td>{lab}</td>{#each series as s (s.label)}<td>{fmt(s.values[i] || 0)}</td>{/each}</tr>
			{/each}
		</tbody>
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
	.band {
		fill: var(--mint);
		opacity: 0.45;
	}
	.tick {
		font-size: 10px;
		fill: var(--muted);
		font-weight: 600;
	}
	.legend {
		display: flex;
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
