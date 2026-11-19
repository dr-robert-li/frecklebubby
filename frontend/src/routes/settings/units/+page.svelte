<script lang="ts">
	import { api } from '#lib/api.ts';
	import { app, toast, type Settings } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';

	let error = $state('');
	const groups = [
		['volume', 'Volume', [['ml', 'ml'], ['oz', 'oz']]],
		['weight', 'Weight', [['kg', 'kg'], ['lb', 'lb']]],
		['length', 'Length', [['cm', 'cm'], ['in', 'in']]],
		['temperature', 'Temperature', [['C', '°C'], ['F', '°F']]]
	] as const;

	async function patch(body: object) {
		error = '';
		try {
			app.settings = await api<Settings>('/family/settings', { method: 'PATCH', body });
			toast('Saved');
		} catch (e) {
			error = (e as Error).message;
		}
	}
</script>

<Back title="Units and wording" />
<p class="muted">For the whole family. We store the same data, only the display changes.</p>
{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="card stack">
	{#each groups as [key, label, opts] (key)}
		<div>
			<span class="field-label" id="u-{key}">{label}</span>
			<div class="seg" role="group" aria-labelledby="u-{key}">
				{#each opts as [v, l] (v)}
					<button aria-pressed={app.settings?.units[key] === v} onclick={() => patch({ units: { [key]: v } })}>{l}</button>
				{/each}
			</div>
		</div>
	{/each}
	<div>
		<span class="field-label" id="u-word">Word for nappy</span>
		<div class="seg" role="group" aria-labelledby="u-word">
			{#each [['nappy', 'Nappy'], ['diaper', 'Diaper']] as [v, l] (v)}
				<button aria-pressed={app.settings?.wording === v} onclick={() => patch({ wording: v })}>{l}</button>
			{/each}
		</div>
	</div>
</section>
