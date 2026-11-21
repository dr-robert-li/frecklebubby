<script lang="ts">
	// Sleep training: an option, off by default. The parent selects a method and a pace on a scale; the page shows
	// the steps for tonight; the parent reports each night. With the mode off, the sleep plan works as before.
	import { api } from './api.ts';
	import { child } from './app.svelte.ts';
	import Cites from './Cites.svelte';
	import { fmtDay, localDay } from './format.svelte.ts';
	import type { Citation } from './SourceSheet.svelte';

	type Night = { night: number; date: string; pace: number; minutes_to_sleep: number | null; wakes: number | null; crying_minutes: number | null; answer: string };
	type Training = {
		id: number; method: string; method_name: string; presence: boolean; pace: number; auto_pace: boolean;
		status: 'active' | 'paused'; goal_bedtime: string | null; nights: Night[];
		tonight: { night: number; bedtime: string | null; steps: string[] };
		review: { kind: string; text: string } | null; pause_hint: boolean;
	};
	type State = {
		gate: { available: boolean; methods: string[]; warning: string | null; reason: string | null };
		training: Training | null; scale: { min: number; max: number }; sources: Citation[];
	};

	let { onchange }: { onchange: () => void } = $props();
	const cid = $derived(child()?.id);
	const name = $derived(child()?.name ?? 'your child');
	let st = $state<State | null>(null);
	let error = $state('');
	let busy = $state(false);
	let setup = $state(false);
	let form = $state({ method: 'graduated', presence: false, pace: 5, auto_pace: true, goal_bedtime: '19:30', confirm: false });
	const yesterday = () => localDay(Date.now() - 86400_000);
	let rep = $state({ day: yesterday(), minutes_to_sleep: '', wakes: '', crying_minutes: '', answer: 'ok' });

	const ABOUT: Record<string, [string, string]> = {
		graduated: ['Graduated extinction', 'You leave the room. When your child cries, you wait some minutes, then go in for a short check. With parental presence you stay in the room and move away in steps.'],
		extinction: ['Extinction', 'You leave the room and do not go back in until the morning. It has the strongest evidence, but some sources do not recommend it, because many parents find it too hard to do. With parental presence you stay in the room for 7 nights.'],
		fading: ['Bedtime fading', 'You start with a late bedtime, at which your child falls asleep fast. Then bedtime moves earlier in small steps. No crying is necessary.']
	};
	const paceWord = (p: number) => (p <= 2 ? 'very gentle' : p <= 4 ? 'gentle' : p <= 6 ? 'the usual pace of the studies' : p <= 8 ? 'firm' : 'very firm');

	$effect(() => {
		if (cid) load();
	});

	async function call(method: 'GET' | 'PUT' | 'POST' | 'DELETE', body?: object, path = '') {
		busy = true;
		error = '';
		try {
			st = await api<State>(`/children/${cid}/sleep/training${path}`, method === 'GET' ? {} : { method, body });
			if (st.gate.methods.length && !st.gate.methods.includes(form.method)) form.method = st.gate.methods[0];
			if (method !== 'GET') onchange();
			return true;
		} catch (e) {
			error = (e as Error).message;
			return false;
		} finally {
			busy = false;
		}
	}
	const load = () => call('GET');

	async function start(e: Event) {
		e.preventDefault();
		const body = { method: form.method, presence: form.presence, pace: form.pace, auto_pace: form.auto_pace, confirm_warning: form.confirm, ...(form.method === 'fading' ? { goal_bedtime: form.goal_bedtime } : {}) };
		if (await call('PUT', body)) setup = false;
	}

	async function report(e: Event) {
		e.preventDefault();
		const n = (v: string) => (v === '' ? null : Number(v));
		if (await call('POST', { day: rep.day, minutes_to_sleep: n(rep.minutes_to_sleep), wakes: n(rep.wakes), crying_minutes: n(rep.crying_minutes), answer: rep.answer }, '/nights'))
			rep = { day: yesterday(), minutes_to_sleep: '', wakes: '', crying_minutes: '', answer: 'ok' };
	}
</script>

<section class="card" aria-label="Sleep training">
	<h2>Sleep training</h2>
	{#if !st}
		{#if error}<p class="notice">{error}</p>{:else}<p class="muted">Loading…</p>{/if}
	{:else if st.training}
		{@const t = st.training}
		<p class="muted small">{t.method_name}{t.presence ? ', with parental presence' : ''}. {t.status === 'paused' ? 'Paused.' : `Night ${t.tonight.night}.`}</p>
		{#if t.pause_hint && t.status === 'active'}<p class="notice">A fever or a medicine is logged in the last 24 hours. Do not train when {name} is ill. Pause the sleep training until {name} is well.</p>{/if}
		{#if t.review}<p class="notice" role="status">{t.review.text}</p>{/if}
		{#if t.status === 'active'}
			<h3>Tonight</h3>
			<ol class="steps">
				{#each t.tonight.steps as step, i (i)}<li>{step}</li>{/each}
			</ol>
		{/if}

		<h3>Pace</h3>
		<label class="field"><span>Scale: {t.pace} of {st.scale.max}, {paceWord(t.pace)}</span>
			<input type="range" min={st.scale.min} max={st.scale.max} step="1" value={t.pace} disabled={busy} aria-label="Pace, from gentle to firm"
				onchange={(e) => call('PUT', { pace: Number((e.currentTarget as HTMLInputElement).value) })} /></label>
		<p class="ends muted small"><span>Gentle</span><span>Firm</span></p>
		<fieldset>
			<legend class="sr-only">How the scale changes</legend>
			<label class="pick"><input type="radio" name="auto" checked={t.auto_pace} onchange={() => call('PUT', { auto_pace: true })} /> Change the scale each night from my answers</label>
			<label class="pick"><input type="radio" name="auto" checked={!t.auto_pace} onchange={() => call('PUT', { auto_pace: false })} /> Keep the scale. I change it by hand</label>
		</fieldset>
		<p class="muted small">A change is for the next night. Do not change the steps in the night.</p>

		<h3>Report a night</h3>
		<form class="stack" onsubmit={report}>
			<label class="field"><span>Evening of</span><input type="date" bind:value={rep.day} max={localDay()} required /></label>
			<label class="field"><span>Minutes from bed to asleep</span><input type="number" inputmode="numeric" min="0" max="600" bind:value={rep.minutes_to_sleep} /></label>
			<label class="field"><span>Wakes in the night</span><input type="number" inputmode="numeric" min="0" max="30" bind:value={rep.wakes} /></label>
			<label class="field"><span>Minutes of crying (optional)</span><input type="number" inputmode="numeric" min="0" max="600" bind:value={rep.crying_minutes} /></label>
			<fieldset>
				<legend>How was the night for you?</legend>
				{#each [['too_hard', 'Too hard'], ['ok', 'All right'], ['faster', 'It can go faster']] as [k, l] (k)}
					<label class="pick"><input type="radio" name="answer" checked={rep.answer === k} onchange={() => (rep.answer = k)} /> {l}</label>
				{/each}
			</fieldset>
			<button class="wide" type="submit" disabled={busy}>Save the night</button>
		</form>

		{#if t.nights.length}
			<h3>Nights so far</h3>
			<ul class="nights">
				{#each [...t.nights].reverse() as n (n.date)}
					<li><strong>{n.night}.</strong> {fmtDay(n.date, { day: 'numeric', month: 'short' })}: {n.minutes_to_sleep ?? '–'} min to sleep, {n.wakes ?? '–'} wakes, pace {n.pace}{n.answer === 'too_hard' ? ', too hard' : n.answer === 'faster' ? ', can go faster' : ''}</li>
				{/each}
			</ul>
		{/if}
		{#if error}<p class="notice" role="alert">{error}</p>{/if}
		<div class="row">
			{#if t.status === 'active'}
				<button class="ghost" disabled={busy} onclick={() => call('PUT', { status: 'paused' })}>Pause</button>
			{:else}
				<button disabled={busy} onclick={() => call('PUT', { status: 'active' })}>Continue</button>
			{/if}
			<button class="ghost" disabled={busy} onclick={() => call('DELETE')}>End sleep training</button>
		</div>
		<Cites list={st.sources} />
	{:else if !st.gate.available}
		<p class="muted">{st.gate.reason}</p>
	{:else if !setup}
		<p class="muted">An option for parents who want it. It is off now, and the sleep plan works with no sleep training. You select a method and a pace. You can stop at any time.</p>
		<button class="ghost wide" onclick={() => (setup = true)}>Set up sleep training</button>
	{:else}
		<form class="stack" onsubmit={start}>
			{#if st.gate.warning}
				<p class="notice">{st.gate.warning}</p>
				<label class="pick"><input type="checkbox" bind:checked={form.confirm} required /> I read this, and I want to start</label>
			{/if}
			<fieldset>
				<legend>Method</legend>
				{#each st.gate.methods as m (m)}
					<label class="pick method"><input type="radio" name="method" checked={form.method === m} onchange={() => (form.method = m)} />
						<span><strong>{ABOUT[m][0]}</strong><br /><span class="muted small">{ABOUT[m][1]}</span></span></label>
				{/each}
			</fieldset>
			<label class="pick"><input type="checkbox" bind:checked={form.presence} /> With parental presence: I stay in the room</label>
			{#if form.method === 'fading'}
				<label class="field"><span>The bedtime that you want to reach</span><input type="time" bind:value={form.goal_bedtime} required /></label>
			{/if}
			<label class="field"><span>Pace: {form.pace} of {st.scale.max}, {paceWord(form.pace)}</span>
				<input type="range" min={st.scale.min} max={st.scale.max} step="1" bind:value={form.pace} aria-label="Pace, from gentle to firm" /></label>
			<p class="ends muted small"><span>Gentle</span><span>Firm</span></p>
			<fieldset>
				<legend>The scale</legend>
				<label class="pick"><input type="radio" name="auto0" checked={form.auto_pace} onchange={() => (form.auto_pace = true)} /> Change the scale each night from my answers</label>
				<label class="pick"><input type="radio" name="auto0" checked={!form.auto_pace} onchange={() => (form.auto_pace = false)} /> Keep the scale. I change it by hand</label>
			</fieldset>
			<p class="muted small">Long-term studies found no harm from these methods. Sleep training is a choice. It is not necessary. A feed that {name} still needs at night stays.</p>
			{#if error}<p class="notice" role="alert">{error}</p>{/if}
			<div class="row">
				<button type="submit" disabled={busy}>Start sleep training</button>
				<button type="button" class="ghost" onclick={() => ((setup = false), (error = ''))}>Cancel</button>
			</div>
		</form>
		<Cites list={st.sources} />
	{/if}
	<p class="disclaimer">General information, not medical advice.</p>
</section>

<style>
	.steps {
		padding-left: 22px;
		margin: 0 0 12px;
	}
	.steps li,
	.nights li {
		margin-bottom: 6px;
	}
	.nights {
		list-style: none;
		padding: 0;
		margin: 0 0 12px;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin: 8px 0;
	}
	.pick {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		padding: 6px 0;
	}
	.pick.method {
		padding: 8px 0;
	}
	input[type='range'] {
		width: 100%;
		padding: 0;
		accent-color: var(--accent);
	}
	.ends {
		display: flex;
		justify-content: space-between;
		margin: 0 0 8px;
	}
	.row {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		margin: 12px 0;
	}
</style>
