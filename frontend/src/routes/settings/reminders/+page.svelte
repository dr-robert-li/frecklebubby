<script lang="ts">
	import { api } from '#lib/api.ts';
	import { app, toast, wording } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import Icon from '#lib/Icon.svelte';
	import Sheet from '#lib/Sheet.svelte';
	import { tracker, trackers } from '#lib/trackers.ts';

	type Reminder = { id: number; child_id: number; type: string; mode: 'in' | 'at'; interval_minutes: number | null; times: string[]; days: number[]; daytime_only: boolean; enabled: boolean };
	const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
	let childId = $state(app.childId);
	let list = $state<Reminder[]>([]);
	let error = $state('');
	let adding = $state(false);
	// new reminder form
	let type = $state('nappy');
	let mode = $state<'in' | 'at'>('in');
	let hours = $state(3);
	let minutes = $state(0);
	let before = $state(15);
	let times = $state<string[]>(['08:00']);
	let days = $state<number[]>([]);
	let daytimeOnly = $state(false);
	let formError = $state('');

	const load = async () => {
		if (childId) list = await api<Reminder[]>(`/children/${childId}/reminders`).catch((e) => ((error = e.message), []));
	};
	$effect(() => {
		void childId;
		load();
	});

	const typeLabel = (t: string) => (t === 'sleep_alert' ? 'Next sleep alert' : tracker(t, wording()).label);
	function describe(r: Reminder) {
		if (r.type === 'sleep_alert') return `${r.interval_minutes} min before the next sleep window`;
		const when = r.mode === 'in'
			? `${Math.floor(r.interval_minutes! / 60) ? `${Math.floor(r.interval_minutes! / 60)} h ` : ''}${r.interval_minutes! % 60 ? `${r.interval_minutes! % 60} min ` : ''}after the last one`
			: `at ${r.times.join(', ')}`;
		const d = r.days.length && r.days.length < 7 ? ` on ${r.days.map((x) => DAYS[x]).join(', ')}` : '';
		return when + d + (r.daytime_only ? ', daytime only' : '');
	}

	async function create(e: SubmitEvent) {
		e.preventDefault();
		formError = '';
		const alert = type === 'sleep_alert';
		const m = alert ? 'in' : mode;
		const interval = alert ? before : hours * 60 + minutes;
		if (m === 'in' && interval < 1) return void (formError = 'Set a time of 1 minute or more.');
		if (m === 'at' && !times.filter(Boolean).length) return void (formError = 'Add a time.');
		try {
			await api(`/children/${childId}/reminders`, {
				method: 'POST',
				body: { type, mode: m, interval_minutes: m === 'in' ? interval : null, times: m === 'at' ? times.filter(Boolean) : [], days, daytime_only: daytimeOnly }
			});
			toast('Reminder saved');
			adding = false;
			load();
		} catch (err) {
			formError = (err as Error).message;
		}
	}

	async function toggle(r: Reminder) {
		await api(`/reminders/${r.id}`, { method: 'PATCH', body: { enabled: !r.enabled } }).catch((e) => (error = e.message));
		load();
	}
	async function remove(r: Reminder) {
		await api(`/reminders/${r.id}`, { method: 'DELETE' }).catch((e) => (error = e.message));
		toast('Reminder deleted');
		load();
	}
	function openAdd() {
		type = 'nappy';
		mode = 'in';
		hours = 3;
		minutes = 0;
		times = ['08:00'];
		days = [];
		daytimeOnly = false;
		formError = '';
		adding = true;
	}
</script>

<Back title="Reminders" />
<p class="muted">Reminders show in the app and as push messages on devices where you turn them on.</p>
{#if (app.me?.children.length ?? 0) > 1}
	<label class="field"><span>Child</span>
		<select bind:value={childId}>{#each app.me!.children as c (c.id)}<option value={c.id}>{c.name}</option>{/each}</select></label>
{/if}
{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="card">
	{#if list.length}
		<ul class="list">
			{#each list as r (r.id)}
				<li class="rem">
					<span class="txt"><strong>{typeLabel(r.type)}</strong><span class="muted small">{describe(r)}</span></span>
					<label class="switch"><input type="checkbox" checked={r.enabled} onchange={() => toggle(r)} aria-label="{typeLabel(r.type)} reminder on" /></label>
					<button class="icon" aria-label="Delete {typeLabel(r.type)} reminder" onclick={() => remove(r)}><Icon name="trash" size={20} /></button>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="empty">No reminders yet.</p>
	{/if}
	<button class="ghost wide" onclick={openAdd}><Icon name="plus" /> Add a reminder</button>
</section>

{#if adding}
	<Sheet title="New reminder" onclose={() => (adding = false)}>
		<form class="stack" onsubmit={create}>
			<label class="field"><span>Remind me about</span>
				<select bind:value={type}>
					{#each trackers(wording()).filter((t) => t.type !== 'note' && t.type !== 'cry') as t (t.type)}<option value={t.type}>{t.label}</option>{/each}
					<option value="sleep_alert">Next sleep (alert before the window)</option>
				</select></label>
			{#if type === 'sleep_alert'}
				<label class="field"><span>Minutes before the sleep window</span><input type="number" min="1" max="240" bind:value={before} /></label>
			{:else}
				<div class="seg" role="group" aria-label="Kind of reminder">
					<button type="button" aria-pressed={mode === 'in'} onclick={() => (mode = 'in')}>Remind in</button>
					<button type="button" aria-pressed={mode === 'at'} onclick={() => (mode = 'at')}>Remind at</button>
				</div>
				{#if mode === 'in'}
					<p class="muted small">Time after the last {typeLabel(type).toLowerCase()} entry.</p>
					<div class="two">
						<label class="field"><span>Hours</span><input type="number" min="0" max="168" bind:value={hours} /></label>
						<label class="field"><span>Minutes</span><input type="number" min="0" max="59" bind:value={minutes} /></label>
					</div>
				{:else}
					<fieldset>
						<legend class="field-label">Times</legend>
						{#each times as _, i (i)}
							<div class="row timein">
								<input type="time" bind:value={times[i]} aria-label="Time {i + 1}" />
								{#if times.length > 1}<button type="button" class="icon" aria-label="Remove time {i + 1}" onclick={() => times.splice(i, 1)}><Icon name="close" /></button>{/if}
							</div>
						{/each}
						<button type="button" class="plain" onclick={() => times.push('12:00')}><Icon name="plus" /> Add a time</button>
					</fieldset>
				{/if}
				<fieldset>
					<legend class="field-label">Days (none = every day)</legend>
					<div class="chips">
						{#each DAYS as d, i (d)}
							<button type="button" class="chip day" aria-pressed={days.includes(i)} onclick={() => (days = days.includes(i) ? days.filter((x) => x !== i) : [...days, i].sort())}>{d}</button>
						{/each}
					</div>
				</fieldset>
			{/if}
			<label class="check"><input type="checkbox" bind:checked={daytimeOnly} /> Daytime only (not at night)</label>
			{#if formError}<p class="error" role="alert">{formError}</p>{/if}
			<button class="wide" type="submit">Save reminder</button>
		</form>
	</Sheet>
{/if}

<style>
	.rem {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.txt {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.txt strong {
		color: var(--ink-strong);
	}
	.switch {
		width: 48px;
		height: 48px;
		display: grid;
		place-items: center;
	}
	.two {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin-inline: 0;
	}
	.timein {
		margin-bottom: 8px;
	}
	.day {
		padding: 8px 12px;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 48px;
		font-weight: 700;
	}
</style>
