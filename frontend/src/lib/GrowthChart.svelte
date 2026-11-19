<script lang="ts">
	// WHO percentile bands (P3–P97, P15–P85, P50) with the child's measurements.
	type Curve = { age_months: number; p3: number; p15: number; p50: number; p85: number; p97: number };
	type Pt = { age: number; v: number; pct: number | null };
	let { curve, points, conv, unit }: { curve: Curve[]; points: Pt[]; conv: (v: number) => number; unit: string } = $props();

	const W = 340, H = 220, L = 36, B = 24, T = 10, R = 30;
	const lastAge = $derived(Math.max(0, ...points.map((p) => p.age)));
	const xmax = $derived(Math.min(curve.at(-1)?.age_months ?? 24, Math.max(6, Math.ceil((lastAge + 3) / 3) * 3)));
	const cv = $derived(curve.filter((c) => c.age_months <= xmax));
	const ymin = $derived(Math.floor(Math.min(...cv.map((c) => conv(c.p3)), ...points.map((p) => p.v))));
	const ymax = $derived(Math.ceil(Math.max(...cv.map((c) => conv(c.p97)), ...points.map((p) => p.v))));
	const x = (a: number) => L + (a / xmax) * (W - L - R);
	const y = (v: number) => H - B - ((v - ymin) / (ymax - ymin || 1)) * (H - B - T);
	const line = (k: keyof Curve) => cv.map((c) => `${x(c.age_months)},${y(conv(c[k]))}`).join(' ');
	const area = (lo: keyof Curve, hi: keyof Curve) =>
		[...cv.map((c) => `${x(c.age_months)},${y(conv(c[hi]))}`), ...[...cv].reverse().map((c) => `${x(c.age_months)},${y(conv(c[lo]))}`)].join(' ');
	const xt = $derived(Array.from({ length: 4 }, (_, i) => Math.round((xmax / 3) * i)));
	const yt = $derived([ymin, (ymin + ymax) / 2, ymax]);
</script>

<svg viewBox="0 0 {W} {H}" role="img" aria-label="Growth chart with WHO percentile curves">
	<polygon points={area('p3', 'p97')} class="outer" />
	<polygon points={area('p15', 'p85')} class="inner" />
	<polyline points={line('p50')} class="median" />
	{#each [['p97', 'P97'], ['p50', 'P50'], ['p3', 'P3']] as [k, l] (k)}
		{@const c = cv.at(-1)}
		{#if c}<text x={W - R + 4} y={y(conv(c[k as keyof Curve])) + 4} class="tick">{l}</text>{/if}
	{/each}
	{#each yt as v (v)}
		<line x1={L} x2={W - R} y1={y(v)} y2={y(v)} class="grid" />
		<text x={L - 6} y={y(v) + 4} class="tick" text-anchor="end">{Math.round(v * 10) / 10}</text>
	{/each}
	{#each xt as a (a)}
		<text x={x(a)} y={H - 6} class="tick" text-anchor="middle">{a} mo</text>
	{/each}
	<polyline points={points.map((p) => `${x(p.age)},${y(p.v)}`).join(' ')} class="kid" />
	{#each points as p, i (i)}
		<circle cx={x(p.age)} cy={y(p.v)} r="5.5" class="pt"><title>{p.v} {unit} at {p.age.toFixed(1)} months{p.pct != null ? `, ${Math.round(p.pct)}th percentile` : ''}</title></circle>
	{/each}
</svg>

<style>
	svg {
		width: 100%;
		height: auto;
		display: block;
	}
	.outer {
		fill: var(--sky);
		opacity: 0.55;
	}
	.inner {
		fill: var(--sky);
	}
	.median {
		fill: none;
		stroke: var(--muted);
		stroke-width: 1.5;
		stroke-dasharray: 4 4;
	}
	.grid {
		stroke: var(--line);
	}
	.tick {
		font-size: 10px;
		fill: var(--muted);
		font-weight: 600;
	}
	.kid {
		fill: none;
		stroke: var(--s1);
		stroke-width: 2;
	}
	.pt {
		fill: var(--s1);
		stroke: var(--surface);
		stroke-width: 2;
	}
</style>
