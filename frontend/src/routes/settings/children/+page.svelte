<script lang="ts">
	import { api } from '#lib/api.ts';
	import { app, loadMe, refresh, selectChild, toast, type Child } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import { ageText, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import Sheet from '#lib/Sheet.svelte';

	const COLOURS = ['#B9A8E8', '#BDE8D3', '#FFD3BF', '#BFE0F6', '#FFEFB0', '#F8C8DC'];
	let list = $state<Child[]>([]);
	let form = $state<(Omit<Partial<Child>, 'sex'> & { sex: string }) | null>(null);
	let error = $state('');
	let busy = $state(false);

	const load = async () => (list = await api<Child[]>('/children?archived=true'));
	$effect(() => void load());

	function open(c?: Child) {
		error = '';
		form = c ? { ...c, sex: c.sex ?? '' } : { name: '', birthdate: '', sex: '', color: COLOURS[list.length % COLOURS.length], night_start: '19:00', morning_cutoff: '07:00' };
	}

	async function save(e: SubmitEvent) {
		e.preventDefault();
		const f = form!;
		busy = true;
		error = '';
		const body = { name: f.name, birthdate: f.birthdate, sex: f.sex || null, color: f.color, night_start: f.night_start, morning_cutoff: f.morning_cutoff };
		try {
			const saved = f.id ? await api<Child>(`/children/${f.id}`, { method: 'PATCH', body }) : await api<Child>('/children', { method: 'POST', body });
			await Promise.all([load(), loadMe()]);
			if (!f.id) selectChild(saved.id);
			else refresh();
			toast(f.id ? 'Child saved' : `${saved.name} added`);
			form = null;
		} catch (err) {
			error = (err as Error).message;
		} finally {
			busy = false;
		}
	}

	async function setArchived(archived: boolean) {
		const f = form!;
		busy = true;
		try {
			await (archived ? api(`/children/${f.id}`, { method: 'DELETE' }) : api(`/children/${f.id}`, { method: 'PATCH', body: { archived: false } }));
			await Promise.all([load(), loadMe()]);
			if (app.childId) selectChild(app.childId);
			toast(archived ? `${f.name} archived` : `${f.name} restored`);
			form = null;
		} catch (err) {
			error = (err as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Back title="Children" />

<section class="card">
	<ul class="list">
		{#each list as c (c.id)}
			<li>
				<button class="kid" onclick={() => open(c)} aria-label="Change {c.name}">
					<span class="dot" style="background:{c.color}"></span>
					<span class="txt"><strong>{c.name}</strong><span class="muted small">{c.archived ? 'Archived' : ageText(c.birthdate)}</span></span>
					<Icon name="right" size={18} />
				</button>
			</li>
		{/each}
	</ul>
	<button class="ghost wide" onclick={() => open()}><Icon name="plus" /> Add a child</button>
</section>

{#if form}
	<Sheet title={form.id ? `Change ${form.name}` : 'Add a child'} onclose={() => (form = null)}>
		<form class="stack" onsubmit={save}>
			<label class="field"><span>Name</span><input bind:value={form.name} required maxlength="100" /></label>
			<label class="field"><span>Date of birth</span><input type="date" bind:value={form.birthdate} required max={localDay()} /></label>
			<fieldset>
				<legend class="field-label">Sex (for growth charts)</legend>
				<div class="chips">
					{#each [['F', 'Girl'], ['M', 'Boy'], ['', 'Not set']] as [v, l] (v)}
						<button type="button" class="chip" aria-pressed={form.sex === v} onclick={() => (form!.sex = v)}>{l}</button>
					{/each}
				</div>
			</fieldset>
			<fieldset>
				<legend class="field-label">Colour</legend>
				<div class="chips">
					{#each COLOURS as col (col)}
						<button type="button" class="swatch" style="background:{col}" aria-label="Colour {col}" aria-pressed={form.color?.toUpperCase() === col} onclick={() => (form!.color = col)}></button>
					{/each}
				</div>
			</fieldset>
			<div class="two">
				<label class="field"><span>Night starts</span><input type="time" bind:value={form.night_start} required /></label>
				<label class="field"><span>Morning starts</span><input type="time" bind:value={form.morning_cutoff} required /></label>
			</div>
			<p class="muted small">We use these times to tell night sleep from naps.</p>
			{#if error}<p class="error" role="alert">{error}</p>{/if}
			<button class="wide" type="submit" disabled={busy}>Save</button>
			{#if form.id}
				{#if form.archived}
					<button type="button" class="ghost wide" disabled={busy} onclick={() => setArchived(false)}>Restore</button>
				{:else}
					<button type="button" class="danger wide" disabled={busy} onclick={() => setArchived(true)}>Archive (hide, keep data)</button>
				{/if}
			{/if}
		</form>
	</Sheet>
{/if}

<style>
	.kid {
		width: 100%;
		background: transparent;
		justify-content: flex-start;
		padding: 4px;
		color: var(--ink);
		text-align: left;
	}
	.txt {
		flex: 1;
		display: flex;
		flex-direction: column;
	}
	.txt strong {
		color: var(--ink-strong);
	}
	.dot {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		flex: none;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin-inline: 0;
	}
	.swatch {
		width: 48px;
		height: 48px;
		padding: 0;
		border: 3px solid transparent;
	}
	.swatch[aria-pressed='true'] {
		border-color: var(--accent);
	}
	.two {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}
</style>
