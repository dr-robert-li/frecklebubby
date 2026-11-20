<script lang="ts">
	import { api, apiRaw } from '#lib/api.ts';
	import { child, units, wording } from '#lib/app.svelte.ts';
	import BarChart from '#lib/BarChart.svelte';
	import { addDays, fmtDay, fmtDur, localDay, round, toUnit, unitLabel, type UnitKind } from '#lib/format.svelte.ts';
	import GrowthChart from '#lib/GrowthChart.svelte';
	import Icon from '#lib/Icon.svelte';
	import SupportReport from '#lib/SupportReport.svelte';

	let end = $state(localDay());
	let report = $state<any>(null);
	let growth = $state<any>(null);
	let metric = $state<'weight' | 'height' | 'head'>('weight');
	let error = $state('');
	let exporting = $state(false);

	$effect(() => {
		const c = child();
		if (!c) return;
		const to = end;
		api(`/children/${c.id}/reports/daily?from=${addDays(to, -6)}&to=${to}`).then((r) => (report = r)).catch((e) => (error = e.message));
	});
	$effect(() => {
		const c = child();
		if (c) api(`/children/${c.id}/growth`).then((g) => (growth = g)).catch((e) => (error = e.message));
	});

	const days = $derived(report?.days ?? []);
	const labels = $derived(days.map((d: any) => fmtDay(d.date, { weekday: 'short' })));
	const hours = (s: number) => Math.round((s / 3600) * 10) / 10;
	const rec = $derived(report?.sleep_recommendations?.[0]);
	const avgSleep = $derived(days.length ? days.reduce((a: number, d: any) => a + d.sleep.total_seconds, 0) / days.length : 0);

	const KIND: Record<string, UnitKind> = { weight: 'weight', height: 'length', head: 'length' };
	const KEY = { weight: 'weight_kg', height: 'height_cm', head: 'head_cm' } as const;
	const conv = (v: number) => round(KIND[metric], toUnit(KIND[metric], v, units()), units());
	const pts = $derived(
		(growth?.points ?? [])
			.filter((p: any) => p[KEY[metric]] != null)
			.map((p: any) => ({ age: p.age_months, v: conv(p[KEY[metric]]), pct: p[`${metric}_percentile`] }))
	);
	const latest = $derived(pts.at(-1));

	async function exportCsv() {
		const c = child()!;
		exporting = true;
		try {
			const res = await apiRaw(`/children/${c.id}/export.csv`);
			if (!res.ok) throw new Error('Export failed. Try again.');
			const a = document.createElement('a');
			a.href = URL.createObjectURL(await res.blob());
			a.download = `frecklebubby-${c.name.toLowerCase().replace(/\W+/g, '-')}-${localDay()}.csv`;
			a.click();
			URL.revokeObjectURL(a.href);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			exporting = false;
		}
	}
</script>

<svelte:head><title>Reports · Frecklebubby</title></svelte:head>

<h1>Reports</h1>
{#if error}<p class="error" role="alert">{error}</p>{/if}

<SupportReport />

<div class="spread week">
	<button class="icon" aria-label="Earlier week" onclick={() => (end = addDays(end, -7))}><Icon name="left" /></button>
	<strong>{fmtDay(addDays(end, -6), { day: 'numeric', month: 'short' })} – {fmtDay(end, { day: 'numeric', month: 'short' })}</strong>
	<button class="icon" aria-label="Later week" disabled={end >= localDay()} onclick={() => (end = addDays(end, 7))}><Icon name="right" /></button>
</div>

{#if report}
	<section class="card">
		<BarChart title="Sleep (hours)" {labels} fmt={(v) => `${Math.round(v * 10) / 10} h`}
			band={rec ? [rec.min_hours, rec.max_hours] : null}
			series={[
				{ label: 'Night', color: 'var(--s1)', values: days.map((d: any) => hours(d.sleep.night_seconds)) },
				{ label: 'Naps', color: 'var(--s2)', values: days.map((d: any) => hours(d.sleep.nap_seconds)) }
			]} />
		<p class="small muted">Average {hours(avgSleep)} h a day.
			{#if rec}Common range for this age: {rec.min_hours}–{rec.max_hours} h (<a href={rec.citation.url} target="_blank" rel="noopener">{rec.citation.publisher} {rec.citation.year ?? ''}</a>).{/if}</p>
	</section>
	<section class="card">
		<BarChart title="Feeds" counts {labels} series={[{ label: 'Feeds', color: 'var(--s1)', values: days.map((d: any) => d.feeds.count) }]} />
		<p class="small muted">Breastfeeding and bottle feeds.</p>
	</section>
	<section class="card">
		<BarChart title={wording() === 'diaper' ? 'Diapers' : 'Nappies'} counts {labels}
			series={[
				{ label: 'Wet', color: 'var(--s1)', values: days.map((d: any) => d.nappies.wet) },
				{ label: 'Dirty', color: 'var(--s2)', values: days.map((d: any) => d.nappies.dirty) }
			]} />
	</section>
	{#if days.some((d: any) => d.play?.count)}
		{@const tr = report.tummy_recommendation}
		<section class="card">
			<BarChart title="Play per day (minutes)" {labels} fmt={(v) => `${Math.round(v)} min`}
				line={tr ? { value: tr.minutes, label: `${tr.minutes} min tummy time` } : null}
				series={[
					{ label: 'Tummy time', color: 'var(--s1)', values: days.map((d: any) => Math.round(d.play.tummy_seconds / 60)) },
					{ label: 'Other play', color: 'var(--s2)', values: days.map((d: any) => Math.round(Math.max(0, d.play.seconds - d.play.tummy_seconds) / 60)) }
				]} />
			<p class="small muted">Indoor play, outdoor play and tummy time with an end time. Time with two timers at once counts once.
				{#if tr}{tr.text} (<a href={tr.citation.url} target="_blank" rel="noopener">WHO {tr.citation.year ?? ''}</a>){/if}</p>
		</section>
	{/if}
	{#if days.some((d: any) => d.confined?.count)}
		<section class="card">
			<BarChart title="Confined time per day (minutes)" {labels} fmt={(v) => `${Math.round(v)} min`}
				series={[{ label: 'Confined', color: 'var(--s1)', values: days.map((d: any) => Math.round(d.confined.seconds / 60)) }]} />
			<p class="small muted">Time in a car seat, pram, bouncer, swing, carrier or high chair. Longest without a break this week:
				{fmtDur(Math.max(...days.map((d: any) => d.confined.longest_seconds)))}.</p>
		</section>
	{/if}
	{#if days.some((d: any) => d.bath_count)}
		<section class="card">
			<BarChart title="Baths" counts {labels} series={[{ label: 'Baths', color: 'var(--s1)', values: days.map((d: any) => d.bath_count) }]} />
			<p class="small muted">{days.reduce((a: number, d: any) => a + d.bath_count, 0)} baths this week.</p>
		</section>
	{/if}
	{#if days.some((d: any) => d.crying?.count)}
		<section class="card">
			<BarChart title="Crying per day (minutes)" {labels} fmt={(v) => `${Math.round(v)} min`}
				series={[{ label: 'Crying', color: 'var(--s1)', values: days.map((d: any) => Math.round(d.crying.seconds / 60)) }]} />
			<p class="small muted">Logged crying times with an end time.</p>
		</section>
	{/if}
{:else if !error}
	<p class="empty">Loading…</p>
{/if}

<section class="card">
	<h2>Growth</h2>
	<div class="seg" role="group" aria-label="Measurement">
		{#each [['weight', 'Weight'], ['height', 'Length'], ['head', 'Head']] as [k, l] (k)}
			<button aria-pressed={metric === k} onclick={() => (metric = k as typeof metric)}>{l}</button>
		{/each}
	</div>
	{#if growth && !growth.sex}
		<p class="notice">Add the child's sex in Settings to see WHO percentile curves.</p>
	{/if}
	{#if growth?.curves?.[metric]?.length}
		<GrowthChart curve={growth.curves[metric]} points={pts} {conv} unit={unitLabel(KIND[metric], units())} />
	{/if}
	{#if latest}
		<p class="latest"><strong>{latest.v} {unitLabel(KIND[metric], units())}</strong>
			{#if latest.pct != null}· {Math.round(latest.pct)}th percentile (WHO){/if}</p>
	{:else if growth}
		<p class="empty">No {metric === 'height' ? 'length' : metric} logged yet. Log one with the Growth tile on Home.</p>
	{/if}
</section>

<section class="card">
	<h2>Export</h2>
	<p class="muted small">All entries of {child()?.name} as a CSV file for a spreadsheet.</p>
	<button class="ghost wide" disabled={exporting} onclick={exportCsv}><Icon name="download" /> Download CSV</button>
</section>

<style>
	.week {
		margin: 4px 0 12px;
	}
	.seg {
		margin: 8px 0 12px;
	}
	.latest {
		margin: 8px 0 0;
		font-size: 1.05rem;
	}
</style>
