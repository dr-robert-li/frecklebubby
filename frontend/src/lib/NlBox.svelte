<script lang="ts">
	// "Tell me what happened…": the model proposes entries, the parent checks them and confirms.
	import { api, softMessage } from './api';
	import { refresh, toast } from './app.svelte';
	import Icon from './Icon.svelte';

	type Proposal = Record<string, any> & { summary: string };
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
	</form>
	{#if busy && !proposals}<p class="muted small" aria-live="polite">Reading…</p>{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if proposals}
		<div class="preview" aria-live="polite">
			{#if message}<p class="small">{message}</p>{/if}
			{#if proposals.length}
				<ul class="list">
					{#each proposals as p, i (i)}
						<li class="spread">
							<span>{p.summary}</span>
							<button class="icon" aria-label="Remove {p.summary}" onclick={() => proposals!.splice(i, 1)}><Icon name="close" size={20} /></button>
						</li>
					{/each}
				</ul>
			{/if}
			<div class="row">
				<button class="ghost" onclick={() => (proposals = null)}>Cancel</button>
				{#if proposals.length}
					<button class="grow" disabled={busy} onclick={commit}><Icon name="check" /> Save {proposals.length === 1 ? 'this' : `these ${proposals.length}`}</button>
				{/if}
			</div>
		</div>
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
	.preview {
		padding: 8px 6px 0;
	}
	.grow {
		flex: 1;
	}
</style>
