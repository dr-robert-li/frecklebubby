<script lang="ts">
	// Bottom sheet on a native <dialog>: focus trap, Esc to close, labelled by its title.
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';

	let { title, onclose, children }: { title: string; onclose: () => void; children: Snippet } = $props();
	let dlg: HTMLDialogElement;
	const id = `sheet-${Math.random().toString(36).slice(2)}`;

	$effect(() => {
		dlg.showModal();
		return () => dlg.open && dlg.close();
	});
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<dialog bind:this={dlg} aria-labelledby={id} oncancel={(e) => (e.preventDefault(), onclose())}
	onclick={(e) => e.target === dlg && onclose()}>
	<div class="sheet">
		<div class="head">
			<h2 {id}>{title}</h2>
			<button class="icon" onclick={onclose} aria-label="Close"><Icon name="close" /></button>
		</div>
		{@render children()}
	</div>
</dialog>

<style>
	dialog {
		border: 0;
		padding: 0;
		margin: auto auto 0;
		width: 100%;
		max-width: 520px;
		max-height: 92dvh;
		background: var(--surface);
		color: var(--ink);
		border-radius: 28px 28px 0 0;
		box-shadow: 0 -8px 30px rgba(0, 0, 0, 0.18);
		animation: up 0.18s ease-out;
	}
	dialog::backdrop {
		background: rgba(30, 24, 44, 0.45);
	}
	.sheet {
		padding: 8px 16px calc(20px + env(safe-area-inset-bottom));
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		position: sticky;
		top: 0;
		background: var(--surface);
		padding: 10px 0 8px;
		z-index: 1;
	}
	.head h2 {
		margin: 0;
	}
	@keyframes up {
		from {
			transform: translateY(40px);
			opacity: 0;
		}
	}
</style>
