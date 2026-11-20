<script lang="ts">
	import { api, softMessage } from '#lib/api.ts';
	import { app, loadMe, refresh } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';

	type Job = { id: number; status: 'pending' | 'running' | 'done' | 'failed'; progress: { stage?: string; children?: number; entries?: Record<string, number>; skipped?: number }; error: string | null };
	let email = $state('');
	let password = $state('');
	let timezone = $state(app.me?.family?.timezone ?? 'Australia/Sydney');
	let job = $state<Job | null>(null);
	let error = $state('');
	let busy = $state(false);
	let into = $state<number | null>(null); // null = new children
	const kids = $derived(app.me?.children ?? []);
	let target = $state('');
	const total = $derived(Object.values(job?.progress.entries ?? {}).reduce((a, b) => a + b, 0));

	async function start(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		error = '';
		try {
			const { job_id } = await api<{ job_id: number }>('/import/huckleberry', { method: 'POST', body: { email, password, timezone, child_id: into } });
			target = kids.find((c) => c.id === into)?.name ?? '';
			password = '';
			poll(job_id);
		} catch (err) {
			error = softMessage(err, 'Import is not available on this server yet.');
			busy = false;
		}
	}

	async function poll(id: number) {
		try {
			job = await api<Job>(`/import/jobs/${id}`);
		} catch (err) {
			error = softMessage(err, 'Lost contact with the import. Try again later.');
			busy = false;
			return;
		}
		if (job.status === 'pending' || job.status === 'running') setTimeout(() => poll(id), 2000);
		else {
			busy = false;
			if (job.status === 'done') {
				await loadMe();
				refresh();
			}
		}
	}
</script>

<Back title="Import from Huckleberry" />
<p class="muted">Copy all children and entries from Huckleberry once. You can run it again: it does not make copies twice. We do not store your Huckleberry password.</p>

<form class="card stack" onsubmit={start}>
	<label class="field"><span>Huckleberry email</span><input type="email" bind:value={email} required autocomplete="off" /></label>
	<label class="field"><span>Huckleberry password</span><input type="password" bind:value={password} required autocomplete="off" /></label>
	<label class="field"><span>Time zone of the data</span><input bind:value={timezone} required /></label>
	{#if kids.length}
		<fieldset class="field">
			<legend>Where does the data go?</legend>
			<label class="pick"><input type="radio" name="into" checked={into === null} onchange={() => (into = null)} /> A new child for each Huckleberry child</label>
			{#each kids as c (c.id)}
				<label class="pick"><input type="radio" name="into" checked={into === c.id} onchange={() => (into = c.id)} /> {c.name} (a child you have now)</label>
			{/each}
			<p class="muted small">Select a child you have now only when the Huckleberry account has one child. That child keeps its name and birth date.</p>
		</fieldset>
	{/if}
	{#if error}<p class="notice" role="alert">{error}</p>{/if}
	<button class="wide" type="submit" disabled={busy}>{busy ? 'Importing…' : 'Start import'}</button>
</form>

{#if job}
	<section class="card" aria-live="polite">
		<h2>{{ pending: 'Waiting to start', running: 'Importing…', done: 'Import complete', failed: 'Import failed' }[job.status]}</h2>
		{#if job.progress.stage && job.status === 'running'}<p class="muted">Now: {job.progress.stage}</p>{/if}
		{#if job.status !== 'failed'}<progress max="1" value={job.status === 'done' ? 1 : undefined} aria-label="Import progress"></progress>{/if}
		{#if job.status === 'done'}<p>{target ? `The data is in the child ${target}.` : 'The data is in new children. Select the child name at the top of the page to change child.'}</p>{/if}
		<p>{job.progress.children ?? 0} {job.progress.children === 1 ? 'child' : 'children'} · {total} entries{job.progress.skipped ? ` · ${job.progress.skipped} skipped` : ''}</p>
		{#if Object.keys(job.progress.entries ?? {}).length}
			<ul class="counts">
				{#each Object.entries(job.progress.entries ?? {}) as [t, n] (t)}<li><span>{t}</span><strong>{n}</strong></li>{/each}
			</ul>
		{/if}
		{#if job.error}<p class="error">{job.error}</p>{/if}
	</section>
{/if}

<style>
	fieldset {
		border: 0;
		padding: 0;
		margin: 0;
	}
	legend {
		font-weight: 700;
		padding: 0;
		margin-bottom: 4px;
	}
	.pick {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 44px;
	}
	progress {
		width: 100%;
		height: 12px;
		accent-color: var(--accent);
		margin: 8px 0;
	}
	.counts {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 6px;
	}
	.counts li {
		background: var(--cloud);
		border-radius: 12px;
		padding: 6px 10px;
		display: flex;
		justify-content: space-between;
	}
</style>
