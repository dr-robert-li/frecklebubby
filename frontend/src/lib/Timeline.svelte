<script lang="ts">
	import { units, wording } from './app.svelte';
	import { fmtTime } from './format.svelte';
	import Icon from './Icon.svelte';
	import { entryDetail, tracker, type Entry } from './trackers';

	let { entries, onpick, empty = 'Nothing logged yet.' }: { entries: Entry[]; onpick: (e: Entry) => void; empty?: string } = $props();
</script>

{#if entries.length}
	<ul class="timeline" aria-label="Timeline">
		{#each entries as e (e.id)}
			{@const t = tracker(e.type, wording())}
			<li>
				<button class="item" onclick={() => onpick(e)} aria-label="Edit {t.label} at {fmtTime(e.started_at)}">
					<span class="time">{fmtTime(e.started_at)}{#if e.ended_at}<br /><span class="muted">{fmtTime(e.ended_at)}</span>{/if}</span>
					<span class="bubble" style="background: var({t.color})"><Icon name={e.type} size={20} /></span>
					<span class="text">
						<strong>{t.label}</strong>
						<span class="detail">{entryDetail(e, units(), wording())}</span>
					</span>
				</button>
			</li>
		{/each}
	</ul>
{:else}
	<p class="empty">{empty}</p>
{/if}

<style>
	.timeline {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.item {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 12px;
		background: transparent;
		border-radius: 18px;
		padding: 8px 6px;
		text-align: left;
		font-weight: 400;
		color: var(--ink);
		justify-content: flex-start;
		min-height: 56px;
	}
	.item:hover {
		background: var(--cloud);
	}
	.time {
		width: 52px;
		flex: none;
		font-size: 0.85rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		line-height: 1.25;
		color: var(--ink-strong);
	}
	.bubble {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		flex: none;
		display: grid;
		place-items: center;
		color: var(--ink-strong);
	}
	.text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.text strong {
		color: var(--ink-strong);
	}
	.detail {
		font-size: 0.9rem;
		color: var(--muted);
		overflow-wrap: anywhere;
	}
</style>
