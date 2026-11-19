<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.ts';
	import { app, loadMe, refresh } from '#lib/app.svelte.ts';
	import { localDay } from '#lib/format.svelte.ts';

	const zones = Intl.supportedValuesOf('timeZone');
	let familyName = $state('');
	let timezone = $state(Intl.DateTimeFormat().resolvedOptions().timeZone || 'Australia/Sydney');
	let name = $state('');
	let birthdate = $state('');
	let sex = $state('');
	let error = $state('');
	let busy = $state(false);
	const step = $derived(app.me?.family ? 2 : 1);

	async function run(fn: () => Promise<unknown>) {
		busy = true;
		error = '';
		try {
			await fn();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	const createFamily = (e: SubmitEvent) => {
		e.preventDefault();
		run(async () => {
			await api('/families', { method: 'POST', body: { name: familyName, timezone } });
			await loadMe();
		});
	};

	const addChild = (e: SubmitEvent) => {
		e.preventDefault();
		run(async () => {
			await api('/children', { method: 'POST', body: { name, birthdate, sex: sex || null } });
			await loadMe();
			refresh();
			goto('/');
		});
	};
</script>

<svelte:head><title>Welcome · Frecklebubby</title></svelte:head>

<div class="hello">
	<img src="/icon.svg" alt="" width="88" height="88" />
	<h1>Welcome to Frecklebubby</h1>
	<p class="muted">Step {step} of 2</p>
</div>

{#if step === 1}
	<form class="card stack" onsubmit={createFamily}>
		<h2>Make your family</h2>
		<p class="muted">You can invite other carers later.</p>
		<label class="field"><span>Family name</span><input bind:value={familyName} required maxlength="100" placeholder="For example: The Lee family" /></label>
		<label class="field"><span>Time zone</span>
			<select bind:value={timezone}>{#each zones as z (z)}<option value={z}>{z.replaceAll('_', ' ')}</option>{/each}</select></label>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<button class="wide" type="submit" disabled={busy}>Next</button>
	</form>
{:else}
	<form class="card stack" onsubmit={addChild}>
		<h2>Add your child</h2>
		<label class="field"><span>Name</span><input bind:value={name} required maxlength="100" /></label>
		<label class="field"><span>Date of birth</span><input type="date" bind:value={birthdate} required max={localDay()} /></label>
		<fieldset>
			<legend class="field-label">Sex (for growth charts)</legend>
			<div class="chips">
				{#each [['F', 'Girl'], ['M', 'Boy'], ['', 'Not now']] as [v, l] (v)}
					<button type="button" class="chip" aria-pressed={sex === v} onclick={() => (sex = v)}>{l}</button>
				{/each}
			</div>
		</fieldset>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<button class="wide" type="submit" disabled={busy}>Start tracking</button>
	</form>
{/if}

<style>
	.hello {
		text-align: center;
		padding: 24px 0 8px;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin-inline: 0;
	}
</style>
