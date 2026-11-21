<script lang="ts">
	import Back from '#lib/Back.svelte';
	import { canVoice, savePrefs, say, voice, type Speak } from '#lib/voice.svelte.ts';

	const p = voice.prefs;
	const SPEAK: [Speak, string][] = [['off', 'Off'], ['handsfree', 'Hands free'], ['all', 'All voice']];
</script>

<svelte:head><title>Voice · Frecklebubby</title></svelte:head>

<Back title="Voice" />
{#if !canVoice()}
	<p class="notice">Voice commands are not available. The server needs the voice part, and the browser needs a microphone.</p>
{:else}
	<p class="muted">Log things and ask questions with your voice. These settings are for this device only.</p>

	<section class="card stack">
		<h2>How to use it</h2>
		<p><strong>Talk button.</strong> Tap the microphone next to a text box, say your words, and tap again. Example: "Wet nappy" or "How much sleep does she need?"</p>
		<p><strong>Hands free.</strong> Tap the wave button. Then say "Hey Bubby" or "OK Bubby" and your words. The app makes a short sound when it hears the keyword. Hands free works while this app is open and the screen is on. The app keeps the screen on.</p>
		<p class="muted small">A voice command saves the entries immediately. When the app is not sure, the entry shows "Not sure". You can undo, change or delete each entry.</p>
		<p class="muted small">Privacy: your server changes the speech into text. With hands free on, each phrase near the phone goes to your server for the keyword check. The server does not keep the sound or the text of other speech.</p>
	</section>

	<section class="card stack">
		<h2>Read the answer aloud</h2>
		<div class="seg" role="group" aria-label="Read the answer aloud">
			{#each SPEAK as [v, l] (v)}
				<button aria-pressed={p.speak === v} onclick={() => ((p.speak = v), savePrefs(), v !== 'off' && say('I read the answers aloud.'))}>{l}</button>
			{/each}
		</div>
		<p class="muted small">The answer also shows on the screen. "Hands free" reads only the answers to "Hey Bubby" commands.</p>
	</section>

	<section class="card stack">
		<h2>Talk button on the side</h2>
		<label class="check"><input type="checkbox" bind:checked={p.float} onchange={savePrefs} /> Show a large hold-to-talk button</label>
		<p class="muted small">For use with one hand. Hold the button down, say your words, and let go. The button shows on all pages.</p>
		{#if p.float}
			<div>
				<span class="field-label" id="side">Side</span>
				<div class="seg" role="group" aria-labelledby="side">
					<button aria-pressed={p.side === 'left'} onclick={() => ((p.side = 'left'), savePrefs())}>Left</button>
					<button aria-pressed={p.side === 'right'} onclick={() => ((p.side = 'right'), savePrefs())}>Right</button>
				</div>
			</div>
			<label class="field"><span>Height on the screen</span>
				<input type="range" min="12" max="80" bind:value={p.y} onchange={savePrefs} aria-valuetext="{p.y} percent from the top" />
			</label>
		{/if}
	</section>
{/if}

<style>
	input[type='range'] {
		padding: 0;
		border: 0;
		accent-color: var(--accent);
	}
	.check {
		display: flex;
		align-items: center;
		gap: 10px;
	}
</style>
