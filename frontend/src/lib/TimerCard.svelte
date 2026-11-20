<script lang="ts">
	// One running timer. Time comes from server state, so it is right after reload and for every carer.
	import { api } from './api';
	import { app, elapsed, refresh, serverNow, sideSeconds, toast, wording, type Timer } from './app.svelte';
	import Cites from './Cites.svelte';
	import { fmtClock, fmtTime, toLocalInput } from './format.svelte';
	import Icon from './Icon.svelte';
	import { activityLabel, deviceLabel, tracker } from './trackers';

	let { timer, childId }: { timer: Timer; childId: number } = $props();
	const t = $derived(tracker(timer.type, wording()));
	const paused = $derived(!!timer.paused_at);
	const title = $derived(
		timer.type === 'activity' ? activityLabel(timer.data.kind) : timer.type === 'confined' ? deviceLabel(timer.data.device) : t.label
	);
	// Confined: the continuous time (with short stops before this timer) and the note or warning for the child's age.
	const conf = $derived(timer.type === 'confined' ? app.status?.confined : null);
	const confSecs = $derived(conf ? ((timer.paused_at ? Date.parse(timer.paused_at) : serverNow()) - Date.parse(conf.since)) / 1000 : 0);
	const level = $derived(
		conf?.warning && confSecs >= conf.warning.after_seconds ? { ...conf.warning, urgent: true }
		: conf?.note && confSecs >= conf.note.after_seconds ? { ...conf.note, urgent: false } : null
	);
	let busy = $state(false);
	let error = $state('');
	let editStart = $state(false);
	let confirmCancel = $state(false);
	let startValue = $state('');

	async function act(action: string, body: Record<string, unknown> = {}, msg = '') {
		busy = true;
		error = '';
		try {
			// Activity timers run one per kind, so each action names its kind.
			if (timer.type === 'activity') body = { ...body, kind: timer.data.kind };
			await api(`/children/${childId}/timers/${timer.type}/${action}`, { method: 'POST', body });
			if (msg) toast(msg);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
			await refresh();
		}
	}
</script>

<section class="timer" style="--c: var({t.color})" aria-label="{title} timer">
	<div class="spread">
		<div>
			<h2>{title}</h2>
			<p class="muted small" aria-live="polite">
				{paused ? 'Paused' : 'Running'} · started {fmtTime(timer.started_at)}
				<button class="plain small" onclick={() => ((startValue = toLocalInput(timer.started_at)), (editStart = !editStart))}>Change</button>
			</p>
		</div>
		<span class="clock" role="timer" aria-label="{title} time">{fmtClock(elapsed(timer))}</span>
	</div>

	{#if timer.type === 'nursing'}
		{@const s = sideSeconds(timer)}
		<div class="sides">
			{#each ['left', 'right'] as side (side)}
				<div class="side" class:on={timer.data.side === side}>
					<span>{side === 'left' ? 'Left' : 'Right'}{timer.data.side === side ? ' (now)' : ''}</span>
					<strong>{fmtClock(side === 'left' ? s.left : s.right)}</strong>
				</div>
			{/each}
		</div>
	{/if}

	{#if conf && conf.since !== timer.started_at}
		<p class="small cont">In a seat since {fmtTime(conf.since)} with short stops: {fmtClock(confSecs)}</p>
	{/if}
	{#if level}
		<article class="card level" class:urgent={level.urgent} role="status">
			<p class="sev">{level.urgent ? 'Time for a break' : 'Good to know'}</p>
			<h3>{level.title}</h3>
			<p>{level.text}</p>
			<Cites list={level.citations} />
		</article>
	{/if}

	{#if editStart}
		<form class="row edit" onsubmit={(e) => (e.preventDefault(), act('start', { at: startValue }, 'Start time changed'), (editStart = false))}>
			<label class="field grow"><span class="sr-only">Start time</span><input type="datetime-local" bind:value={startValue} /></label>
			<button type="submit" disabled={busy}>Save</button>
		</form>
	{/if}

	<div class="actions">
		{#if timer.type === 'nursing'}
			<button class="ghost" disabled={busy} onclick={() => act('switch', {}, 'Side switched')}><Icon name="swap" /> Switch side</button>
		{/if}
		{#if paused}
			<button class="ghost" disabled={busy} onclick={() => act('resume')}><Icon name="play" /> Resume</button>
		{:else}
			<button class="ghost" disabled={busy} onclick={() => act('pause')}><Icon name="pause" /> Pause</button>
		{/if}
		<button class="stop" disabled={busy} onclick={() => act('complete', {}, `${title} saved`)}><Icon name="stop" /> Stop and save</button>
	</div>
	{#if confirmCancel}
		<div class="row confirm">
			<span class="small">Discard this timer?</span>
			<button class="ghost" onclick={() => (confirmCancel = false)}>Keep</button>
			<button class="danger" onclick={() => act('cancel', {}, 'Timer discarded')}>Discard</button>
		</div>
	{:else}
		<button class="plain small discard" onclick={() => (confirmCancel = true)}>Discard timer</button>
	{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
	.timer {
		background: var(--c);
		color: var(--ink-strong);
		border-radius: var(--radius);
		padding: 16px;
		margin-bottom: 14px;
		box-shadow: var(--shadow);
	}
	h2 {
		margin: 0;
	}
	.muted {
		color: var(--ink-strong);
		opacity: 0.85;
		margin: 0;
	}
	.plain {
		min-height: 32px;
		padding: 2px 6px;
		color: var(--ink-strong);
		text-decoration: underline;
	}
	.clock {
		font-size: 2.4rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		letter-spacing: -0.5px;
	}
	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin: 12px 0 0;
	}
	.side {
		background: color-mix(in srgb, var(--surface) 45%, transparent);
		border-radius: 16px;
		padding: 8px 12px;
		display: flex;
		flex-direction: column;
		border: 2px solid transparent;
	}
	.side.on {
		border-color: var(--ink-strong);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 14px;
	}
	.actions button {
		flex: 1 1 auto;
	}
	.actions .ghost {
		background: color-mix(in srgb, var(--surface) 55%, transparent);
	}
	.stop {
		background: var(--ink-strong);
		color: var(--surface);
	}
	.discard {
		margin-top: 4px;
		font-weight: 600;
	}
	.cont {
		margin: 8px 0 0;
	}
	.level {
		margin: 12px 0 0;
		padding: 14px;
		border-left: 8px solid #e2a53a;
		background: var(--surface);
		color: var(--ink);
	}
	.level.urgent {
		border: 3px solid #c2334f;
		border-left-width: 8px;
		background: var(--danger-bg);
		color: var(--danger);
	}
	.level h3 {
		margin: 2px 0 4px;
	}
	.level p {
		margin: 0;
	}
	.sev {
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.edit {
		margin-top: 10px;
	}
	.grow {
		flex: 1;
	}
	.confirm {
		margin-top: 8px;
		flex-wrap: wrap;
	}
</style>
