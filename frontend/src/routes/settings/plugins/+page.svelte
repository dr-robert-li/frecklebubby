<script lang="ts">
	// Options that a plug-in of this server adds (see plugins.py). The page shows only on a server with a plug-in.
	import { api } from '#lib/api.ts';
	import { app, toast } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';

	type Opt = { key: string; label: string; text: string; value: boolean };
	let opts = $state<Opt[] | null>(null);
	let error = $state('');
	const owner = $derived(app.me?.role === 'owner');

	const take = (r: { settings: Opt[] }) => (opts = r.settings);
	$effect(() => {
		api<{ settings: Opt[] }>('/plugins').then(take, (e) => (error = e.message));
	});

	async function set(o: Opt, value: boolean) {
		error = '';
		try {
			take(await api(`/plugins/settings/${o.key}`, { method: 'PUT', body: { value } }));
			toast('Saved');
		} catch (e) {
			error = (e as Error).message;
		}
	}
</script>

<Back title="Options of this server" />
<p class="muted">For the whole family. {owner ? '' : 'Only the family owner can change these options.'}</p>
{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if opts}
	{#each opts as o (o.key)}
		<section class="card stack">
			<label class="pick"><input type="checkbox" checked={o.value} disabled={!owner} onchange={(e) => set(o, e.currentTarget.checked)} /> <strong>{o.label}</strong></label>
			<p class="muted small text">{o.text}</p>
		</section>
	{/each}
{:else if !error}
	<p class="muted">Loading…</p>
{/if}

<style>
	.pick {
		display: flex;
		gap: 10px;
		align-items: flex-start;
	}
	.text {
		white-space: pre-line;
		margin: 0;
	}
</style>
