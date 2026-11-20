<script lang="ts" module>
	export type Proposal = Record<string, any> & { summary: string; unsure?: string };
</script>

<script lang="ts">
	// Proposals from plain words: the parent removes what is wrong, then saves or cancels (Home box and assistant).
	import Icon from './Icon.svelte';

	let {
		proposals = $bindable(),
		message = '',
		busy = false,
		oncancel,
		onsave
	}: { proposals: Proposal[]; message?: string; busy?: boolean; oncancel: () => void; onsave: () => void } = $props();
</script>

<div class="preview" aria-live="polite">
	{#if message}<p class="small">{message}</p>{/if}
	{#if proposals.length}
		<ul class="list">
			{#each proposals as p, i (i)}
				<li class="spread">
					<span>{p.summary}{#if p.unsure}<br /><span class="muted small">Not sure: {p.unsure}</span>{/if}</span>
					<button class="icon" aria-label="Remove {p.summary}" onclick={() => proposals.splice(i, 1)}><Icon name="close" size={20} /></button>
				</li>
			{/each}
		</ul>
	{/if}
	<div class="row">
		<button class="ghost" onclick={oncancel}>Cancel</button>
		{#if proposals.length}
			<button class="grow" disabled={busy} onclick={onsave}><Icon name="check" /> Save {proposals.length === 1 ? 'this' : `these ${proposals.length}`}</button>
		{/if}
	</div>
</div>

<style>
	.preview {
		padding: 8px 6px 0;
	}
	.grow {
		flex: 1;
	}
</style>
