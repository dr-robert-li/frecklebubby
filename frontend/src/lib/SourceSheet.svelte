<script lang="ts" module>
	export type Citation = { n: number; title: string; publisher?: string; author?: string; url?: string; year?: number; kind: string; licence?: string };
</script>

<script lang="ts">
	// Details of one citation, with a link to the source.
	import Icon from './Icon.svelte';
	import Sheet from './Sheet.svelte';

	let { source, onclose }: { source: Citation; onclose: () => void } = $props();
</script>

<Sheet title="Source" {onclose}>
	<div class="stack">
		<h3>[{source.n}] {source.title}</h3>
		<p class="muted">
			{[source.author, source.publisher, source.year].filter(Boolean).join(' · ')}<br />
			{{ bundled: 'From the built-in library', link: 'Trusted source (link only)', upload: 'Your family upload', web: 'Read from an approved website' }[source.kind] ?? ''}
			{#if source.licence}· Licence: {source.licence}{/if}
		</p>
		{#if source.url}<a class="btn wide" href={source.url} target="_blank" rel="noopener"><Icon name="link" /> Open source</a>{/if}
	</div>
</Sheet>
