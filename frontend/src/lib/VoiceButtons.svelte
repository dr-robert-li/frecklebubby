<script lang="ts">
	// Two buttons next to a text box: push to talk (tap to start, tap to stop) and hands free (on or off).
	import Icon from './Icon.svelte';
	import { canVoice, pttToggle, setHandsFree, voice } from './voice.svelte';
</script>

{#if canVoice()}
	<button class="icon mic" class:on={voice.recording} type="button" disabled={voice.busy && !voice.recording} aria-pressed={voice.recording}
		aria-label={voice.recording ? 'Stop recording and send' : 'Talk: start recording'} onclick={pttToggle}>
		<Icon name={voice.recording ? 'stop' : 'mic'} />
	</button>
	<button class="icon hf" class:on={voice.handsFree} type="button" aria-pressed={voice.handsFree}
		aria-label={voice.handsFree ? 'Hands free is on. Turn it off' : 'Hands free: listen for "Hey Bubby"'} onclick={() => setHandsFree(!voice.handsFree)}>
		<Icon name="wave" />
	</button>
{/if}

<style>
	button {
		background: var(--cloud);
		flex: none;
	}
	.mic.on {
		background: var(--rose, #f6b6b6);
		animation: pulse 1.2s ease-in-out infinite;
	}
	.hf.on {
		background: var(--accent);
		color: var(--surface);
	}
	@keyframes pulse {
		50% {
			opacity: 0.55;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.mic.on {
			animation: none;
		}
	}
</style>
