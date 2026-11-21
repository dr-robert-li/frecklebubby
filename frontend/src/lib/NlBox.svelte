<script lang="ts">
	// "Tell me what happened…": the model proposes entries, the parent checks them and confirms.
	import { api, softMessage } from './api';
	import { refresh, toast } from './app.svelte';
	import Icon from './Icon.svelte';
	import Proposals, { type Proposal } from './Proposals.svelte';
	import VoiceButtons from './VoiceButtons.svelte';

	let { childId }: { childId: number } = $props();
	let text = $state('');
	let proposals = $state<Proposal[] | null>(null);
	let message = $state('');
	let error = $state('');
	let busy = $state(false);

	async function parse(e: SubmitEvent) {
		e.preventDefault();
		if (!text.trim()) return;
		busy = true;
		error = '';
		try {
			const r = await api<{ proposals: Proposal[]; message: string }>(`/children/${childId}/nl/parse`, { method: 'POST', body: { text } });
			proposals = r.proposals;
			message = r.message;
		} catch (err) {
			error = softMessage(err);
		} finally {
			busy = false;
		}
	}

	async function commit() {
		busy = true;
		error = '';
		try {
			const r = await api<{ created: unknown[]; timers: unknown[] }>(`/children/${childId}/nl/commit`, { method: 'POST', body: { proposals } });
			const n = (r.created?.length ?? 0) + (r.timers?.length ?? 0);
			toast(n === 1 ? 'Saved 1 item' : `Saved ${n} items`);
			text = '';
			proposals = null;
			refresh();
		} catch (err) {
			error = softMessage(err);
		} finally {
			busy = false;
		}
	}
</script>

<section class="card nl" aria-label="Tell me what happened">
	<form class="row" onsubmit={parse}>
		<label for="nl-text" class="sr-only">Tell me what happened</label>
		<input id="nl-text" placeholder="Tell me what happened…" bind:value={text} autocomplete="off" />
		<button class="icon send" type="submit" disabled={busy || !text.trim()} aria-label="Read my words"><Icon name="sparkle" /></button>
		<VoiceButtons />
	</form>
	{#if busy && !proposals}<p class="muted small" aria-live="polite">Reading…</p>{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if proposals}
		<Proposals bind:proposals {message} {busy} oncancel={() => (proposals = null)} onsave={commit} />
	{/if}
</section>

<style>
	.nl {
		padding: 10px;
	}
	.nl input {
		border: 0;
		background: var(--cloud);
		border-radius: 999px;
	}
	.send {
		background: var(--lavender);
	}
</style>
