<script lang="ts">
	// Citation chips. Tap a chip to see the source.
	import SourceSheet, { type Citation } from './SourceSheet.svelte';

	let { list }: { list: Citation[] } = $props();
	let source = $state<Citation | null>(null);
</script>

{#if list.length}
	<div class="chips cites">
		{#each list as c (c.n)}
			<button class="cite" onclick={() => (source = c)}>[{c.n}] {c.publisher || c.title}</button>
		{/each}
	</div>
{/if}
{#if source}<SourceSheet {source} onclose={() => (source = null)} />{/if}

<style>
	.cites {
		margin-top: 8px;
		gap: 6px;
	}
	.cite {
		min-height: 36px;
		padding: 4px 12px;
		font-size: 0.85rem;
		background: var(--surface);
		border: 1.5px solid var(--line);
	}
</style>
