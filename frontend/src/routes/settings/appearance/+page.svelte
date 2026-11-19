<script lang="ts">
	import { app } from '#lib/app.svelte.ts';
	import { signOut } from '#lib/api.ts';
	import Back from '#lib/Back.svelte';
	import { prefs } from '#lib/format.svelte.ts';
	import { applyTheme, getTheme, type Theme } from '#lib/theme.ts';

	let theme = $state(getTheme());
	function setTheme(t: Theme) {
		theme = t;
		applyTheme(t);
	}
	function setClock(h24: boolean) {
		prefs.clock24 = h24;
		try {
			localStorage.setItem('fb.clock', h24 ? '24' : '12');
		} catch {
			/* this visit only */
		}
	}
</script>

<Back title="Appearance" />
<p class="muted">These settings are for this device only.</p>

<section class="card stack">
	<div>
		<span class="field-label" id="theme">Theme</span>
		<div class="seg" role="group" aria-labelledby="theme">
			{#each [['auto', 'Auto'], ['light', 'Day'], ['dark', 'Night']] as [v, l] (v)}
				<button aria-pressed={theme === v} onclick={() => setTheme(v as Theme)}>{l}</button>
			{/each}
		</div>
		<p class="muted small">Night is dim and calm for feeds in the dark. Auto follows your device.</p>
	</div>
	<div>
		<span class="field-label" id="clock">Clock</span>
		<div class="seg" role="group" aria-labelledby="clock">
			<button aria-pressed={prefs.clock24} onclick={() => setClock(true)}>24-hour</button>
			<button aria-pressed={!prefs.clock24} onclick={() => setClock(false)}>12-hour</button>
		</div>
	</div>
</section>

{#if app.config?.auth_mode === 'clerk'}
	<button class="ghost wide" onclick={signOut}>Sign out</button>
{/if}
