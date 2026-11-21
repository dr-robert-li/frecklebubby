<script lang="ts">
	// On all pages: the state of voice commands, the answer to the last command, and the optional
	// hold-to-talk button on the side of the screen.
	import { api, softMessage } from './api';
	import { app, refresh, toast } from './app.svelte';
	import type { Msg } from './chat';
	import Icon from './Icon.svelte';
	import { canVoice, pttStart, pttStop, setHandsFree, voice } from './voice.svelte';

	const status = $derived(
		voice.recording ? 'Recording… ' : voice.hearing ? (voice.handsFree && !voice.armed ? 'I heard a sound. Checking for "Hey Bubby"…' : 'I heard you. Changing speech to words…') : voice.busy ? 'Working…' : voice.armed ? 'Yes? Say it now.' : voice.handsFree ? 'Hands free is on. Say "Hey Bubby" and then your words.' : voice.turn ? 'Done' : ''
	);
	const paras = (m: Msg) => m.content.replace(/\[\d+\]/g, '').split(/\n\n+/).filter(Boolean);

	async function undo(k: number) {
		const m = voice.turn!;
		try {
			const r = await api<Msg>(`/children/${app.childId}/assistant/messages/${m.id}/undo`, { method: 'POST', body: { item: k } });
			m.logged = r.logged;
			toast('Undone');
			refresh();
		} catch (e) {
			voice.error = softMessage(e);
		}
	}

	function hold(e: PointerEvent) {
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		pttStart();
	}
</script>

{#if canVoice()}
	{#if status || voice.error || voice.turn}
		<aside class="voice card" aria-label="Voice commands">
			<div class="spread">
				<p class="state" role="status">{#if status}<Icon name={voice.handsFree && !voice.recording ? "wave" : "mic"} size={18} /> {status}{/if}</p>
				{#if voice.handsFree}<button class="ghost small" onclick={() => setHandsFree(false)}>Turn off</button>{/if}
				{#if voice.turn || voice.error}
					<button class="icon" aria-label="Close" onclick={() => ((voice.turn = null), (voice.error = ''), (voice.heard = ''))}><Icon name="close" size={20} /></button>
				{/if}
			</div>
			{#if voice.hearing || voice.busy}<div class="bar" role="progressbar" aria-label="Working"></div>{/if}
			{#if voice.busy && !voice.hearing && !voice.turn && voice.heard}<p class="muted small said">You said: {voice.heard}</p>{/if}
			{#if voice.error}<p class="error" role="alert">{voice.error}</p>{/if}
			{#if voice.turn}
				{@const m = voice.turn}
				<div class="turn" aria-live="polite">
					<p class="muted small">You said: {voice.heard}</p>
					{#if m.logged?.items.length}
						<ul class="list">
							{#each m.logged.items as it, k (k)}
								<li class="spread" class:undone={it.undone}>
									<span><Icon name="check" size={16} /> {it.summary}{#if it.unsure}<br /><span class="unsure small">Not sure: {it.unsure}</span>{/if}</span>
									{#if it.undone}<span class="muted small">Undone</span>
									{:else if it.entry_id || it.timer_action === 'start'}<button class="ghost small" aria-label="Undo {it.summary}" onclick={() => undo(k)}>Undo</button>{/if}
								</li>
							{/each}
						</ul>
					{/if}
					{#if m.logged?.proposals.length}<p class="small">{m.logged.message} <a href="/assistant">Open the Assistant</a></p>{/if}
					{#if m.logged && !m.logged.items.length && !m.logged.proposals.length && m.logged.message}<p class="small">{m.logged.message}</p>{/if}
					{#if m.waiting}<p class="muted small">Waiting for the assistant…</p>{/if}
					{#each paras(m) as para, i (i)}<p class:urgent={para.startsWith('Urgent:')}>{para}</p>{/each}
					{#if m.citations.length}<p class="small"><a href="/assistant">See the sources in the Assistant</a></p>{/if}
				</div>
			{/if}
		</aside>
	{/if}

	{#if voice.prefs.float}
		<button class="float {voice.prefs.side}" class:on={voice.recording} style="top: {voice.prefs.y}%" aria-label="Hold to talk" aria-pressed={voice.recording}
			onpointerdown={hold} onpointerup={pttStop} onpointercancel={pttStop} oncontextmenu={(e) => e.preventDefault()}
			onkeydown={(e) => (e.key === ' ' || e.key === 'Enter') && !e.repeat && pttStart()} onkeyup={(e) => (e.key === ' ' || e.key === 'Enter') && pttStop()}>
			<Icon name="mic" size={32} />
		</button>
	{/if}
{/if}

<style>
	.voice {
		position: fixed;
		left: 8px;
		right: 8px;
		bottom: calc(76px + env(safe-area-inset-bottom));
		max-width: 504px;
		margin: 0 auto;
		z-index: 15;
		padding: 10px 12px;
		max-height: 50vh;
		overflow-y: auto;
		border: 2px solid var(--accent);
	}
	.state {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 0;
		font-weight: 700;
		color: var(--ink-strong);
		flex: 1;
	}
	.bar {
		height: 4px;
		margin-top: 8px;
		border-radius: 2px;
		background: linear-gradient(90deg, transparent, var(--accent), transparent) 0 0 / 50% 100% no-repeat;
		animation: slide 1.1s linear infinite;
	}
	@keyframes slide {
		from {
			background-position: -100% 0;
		}
		to {
			background-position: 200% 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.bar {
			animation: none;
			background: var(--accent);
			opacity: 0.5;
		}
	}
	.said {
		margin: 6px 0 0;
	}
	.turn p {
		margin: 6px 0;
	}
	.unsure {
		color: var(--danger, #b3261e);
		font-weight: 700;
	}
	.undone {
		opacity: 0.6;
		text-decoration: line-through;
	}
	.urgent {
		font-weight: 700;
	}
	.float {
		position: fixed;
		z-index: 16;
		width: 76px;
		height: 96px;
		padding: 0;
		transform: translateY(-50%);
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--accent);
		color: var(--surface);
		opacity: 0.45;
		touch-action: none;
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}
	.float.left {
		left: 0;
		border-radius: 0 48px 48px 0;
	}
	.float.right {
		right: 0;
		border-radius: 48px 0 0 48px;
	}
	.float.on {
		opacity: 0.95;
		width: 92px;
	}
</style>
