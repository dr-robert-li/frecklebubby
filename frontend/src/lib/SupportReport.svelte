<script lang="ts">
	// "How can I support <name>?": the saved support report (M11), or make a new one. The model can take a minute.
	import { api, runJob, softMessage } from './api.ts';
	import { child, units, wording } from './app.svelte.ts';
	import Cites from './Cites.svelte';
	import { fmtDay, fmtDur, fmtUnit, localDay } from './format.svelte.ts';
	import Icon from './Icon.svelte';
	import SourceSheet, { type Citation } from './SourceSheet.svelte';

	type Cited = { text: string; cites: number[] };
	type Num = { label: string; value: number; unit: string };
	type Area = {
		area: string; title: string; status: 'ok' | 'watch' | 'no_data'; compared: boolean; numbers: Num[];
		reference: Cited | null; note: string | null; details: string[]; suggestions: Cited[];
		suggested_by: 'model' | 'rules' | null; citations: Citation[];
	};
	type Report = {
		id: number; created_at: string; from: string; to: string; notice: string | null; footer: string;
		urgent: { severity: string; title: string; body: string; citations: Citation[] }[];
		blocks: Area[]; goes_well: Cited & { citations: Citation[] };
	};

	let report = $state<Report | null | undefined>(undefined);
	let busy = $state(false);
	let error = $state('');
	let source = $state<Citation | null>(null);
	const cid = $derived(child()?.id);
	const name = $derived(child()?.name ?? 'your child');

	$effect(() => {
		if (!cid) return;
		report = undefined;
		error = '';
		api<Report | null>(`/children/${cid}/support-report`).then((r) => (report = r)).catch((e) => ((report = null), (error = softMessage(e))));
	});

	async function make() {
		busy = true;
		error = '';
		try {
			report = await runJob<Report>(`/children/${cid}/support-report`);
		} catch (e) {
			error = softMessage(e);
		} finally {
			busy = false;
		}
	}

	const ORDER = { watch: 0, ok: 1, no_data: 2 };
	const shown = $derived((report?.blocks ?? []).filter((b) => b.status !== 'no_data' || b.numbers.length).sort((a, b) => ORDER[a.status] - ORDER[b.status]));
	const empty = $derived((report?.blocks ?? []).filter((b) => b.status === 'no_data' && !b.numbers.length));
	const LABEL = { watch: 'Ideas to try', ok: 'In range', logged: 'Logged', no_data: 'Not enough data' };
	const label = (b: Area) => LABEL[b.status === 'ok' && !b.compared ? 'logged' : b.status];
	const ordinal = (n: number) => n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] ?? 'th');

	function fmt(n: Num): string {
		const u = units();
		if (n.unit === 'h') return fmtDur(n.value * 3600);
		if (n.unit === 'min') return fmtDur(n.value * 60);
		if (n.unit === 'ml') return fmtUnit('volume', n.value, u);
		if (n.unit === 'kg') return fmtUnit('weight', n.value, u);
		if (n.unit === 'cm') return fmtUnit('length', n.value, u);
		if (n.unit === 'percentile') return ordinal(n.value);
		return String(n.value);
	}
	const cite = (list: Citation[], n: number) => list.find((c) => c.n === n);
</script>

{#snippet marks(list: Citation[], cites: number[])}
	{#each cites as n (n)}{@const c = cite(list, n)}{#if c}<button class="mark" onclick={() => (source = c)} aria-label="Source {n}">{n}</button>{/if}{/each}
{/snippet}

<section class="card support" aria-label="Support report">
	<h2>How can I support {name}?</h2>
	{#if report}
		<p class="muted small">Made {fmtDay(localDay(report.created_at), { day: 'numeric', month: 'long' })} · the last 7 days and today</p>
	{:else if report === null}
		<p class="muted">A short report on the last 7 days and today: sleep, feeds, {wording() === 'diaper' ? 'diapers' : 'nappies'}, play, time in a seat, crying, growth and milestones. Each area is compared with a trusted source, with ideas to try.</p>
	{/if}
	{#if error}<p class="notice">{error}</p>{/if}
	<button class="wide" disabled={busy || report === undefined} onclick={make}>
		<Icon name="sparkle" /> {busy ? 'Making the report… this can take a minute or two' : report ? 'Make a new report' : 'Make the report'}
	</button>

	{#if report}
		{#each report.urgent as c, i (i)}
			<article class="urgent" aria-label="Warning: {c.title}">
				<p class="sev">{c.severity === 'urgent' ? 'Urgent' : 'Look at this'}</p>
				<h3>{c.title}</h3>
				<p>{c.body}</p>
				<Cites list={c.citations} />
			</article>
		{/each}
		{#if report.notice}<p class="notice">{report.notice}</p>{/if}
		<p class="well"><Icon name="sparkle" /> <span>{report.goes_well.text}{@render marks(report.goes_well.citations, report.goes_well.cites)}</span></p>

		{#each shown as b (b.area)}
			<article class="area {b.status}" aria-label={b.title}>
				<div class="spread">
					<h3>{b.title}</h3>
					<span class="status">{label(b)}</span>
				</div>
				{#if b.numbers.length}
					<dl>
						{#each b.numbers as n, i (i)}<div><dt>{n.label}</dt><dd>{fmt(n)}</dd></div>{/each}
					</dl>
				{/if}
				{#if b.reference}<p class="small ref">{b.reference.text}{@render marks(b.citations, b.reference.cites)}</p>{/if}
				{#if b.note}<p class="small muted">{b.note}</p>{/if}
				{#if b.details.length}
					<p class="small"><strong>Not yet marked:</strong></p>
					<ul class="small details">{#each b.details as d, i (i)}<li>{d}</li>{/each}</ul>
				{/if}
				{#if b.suggestions.length}
					<h4>Ideas to try{b.suggested_by === 'rules' ? ' (standard tips)' : ''}</h4>
					<ul class="tips">
						{#each b.suggestions as s, i (i)}<li>{s.text}{@render marks(b.citations, s.cites)}</li>{/each}
					</ul>
				{/if}
				<Cites list={b.citations} />
			</article>
		{/each}
		{#if empty.length}<p class="small muted">Nothing logged in these 8 days: {empty.map((b) => b.title).join(', ')}.</p>{/if}
		<p class="disclaimer">{report.footer}</p>
	{/if}
</section>

{#if source}<SourceSheet {source} onclose={() => (source = null)} />{/if}

<style>
	.support > :global(* + *) {
		margin-top: 10px;
	}
	h3 {
		margin: 0;
		font-size: 1.05rem;
	}
	h4 {
		margin: 10px 0 4px;
		font-size: 0.95rem;
	}
	.area {
		border-radius: var(--radius-s);
		padding: 12px;
		background: var(--cloud);
		border-left: 8px solid var(--sky);
	}
	.area.watch {
		border-left-color: #e2a53a;
	}
	.area.ok {
		border-left-color: var(--s2);
	}
	.status {
		flex: none;
		font-size: 0.8rem;
		font-weight: 800;
		padding: 2px 10px;
		border-radius: 999px;
		background: var(--surface);
	}
	dl {
		margin: 8px 0 0;
		display: grid;
		gap: 2px;
	}
	dl div {
		display: flex;
		justify-content: space-between;
		gap: 12px;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
		white-space: nowrap;
		font-weight: 700;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.ref {
		margin: 8px 0 0;
	}
	.tips,
	.details {
		margin: 0;
		padding-left: 20px;
	}
	.tips li + li {
		margin-top: 4px;
	}
	.well {
		display: flex;
		gap: 8px;
		align-items: flex-start;
		background: var(--mint);
		color: var(--ink-strong);
		border-radius: var(--radius-s);
		padding: 10px 14px;
		font-weight: 700;
	}
	.urgent {
		border: 3px solid #c2334f;
		border-left-width: 8px;
		border-radius: var(--radius-s);
		padding: 12px;
		background: var(--danger-bg);
		color: var(--danger);
	}
	.urgent h3 {
		color: var(--danger);
	}
	.sev {
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin: 0 0 2px;
	}
	.mark {
		display: inline-block;
		border-radius: 999px;
		min-height: 24px;
		min-width: 24px;
		padding: 0 6px;
		margin: 0 2px;
		font-size: 0.75rem;
		vertical-align: super;
		background: var(--lavender);
	}
</style>
