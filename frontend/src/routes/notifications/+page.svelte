<script lang="ts">
	import { api } from '#lib/api.ts';
	import { app, refresh, serverNow } from '#lib/app.svelte.ts';
	import { fmtAgo } from '#lib/format.svelte.ts';

	type N = { id: number; child_id: number | null; kind: string; title: string; body: string; created_at: string; read_at: string | null };
	let items = $state<N[] | null>(null);
	let error = $state('');

	async function load() {
		try {
			items = await api<N[]>('/notifications?limit=50');
		} catch (e) {
			error = (e as Error).message;
		}
	}
	$effect(() => void load());

	async function read(n: N) {
		if (n.read_at) return;
		await api(`/notifications/${n.id}/read`, { method: 'POST' }).catch(() => {});
		await load();
		refresh();
	}
	async function readAll() {
		await api('/notifications/read-all', { method: 'POST' }).catch(() => {});
		await load();
		refresh();
	}
	const childName = (id: number | null) => app.me?.children.find((c) => c.id === id)?.name;
</script>

<svelte:head><title>Notifications · Frecklebubby</title></svelte:head>

<div class="spread">
	<h1>Notifications</h1>
	{#if items?.some((n) => !n.read_at)}<button class="plain" onclick={readAll}>Mark all read</button>{/if}
</div>
{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="card">
	{#if items === null}
		<p class="empty">Loading…</p>
	{:else if !items.length}
		<p class="empty">No notifications yet. Set reminders in <a href="/settings/reminders">Settings</a>.</p>
	{:else}
		<ul class="list">
			{#each items as n (n.id)}
				<li>
					<button class="note" class:unread={!n.read_at} onclick={() => read(n)} aria-label="{n.title}{n.read_at ? '' : ', unread'}">
						<span class="title">{#if !n.read_at}<i aria-hidden="true"></i>{/if}{n.title}</span>
						<span class="body">{n.body}</span>
						<span class="muted small">{childName(n.child_id) ?? ''} · {fmtAgo(n.created_at, serverNow())}</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.note {
		width: 100%;
		background: transparent;
		color: var(--ink);
		flex-direction: column;
		align-items: flex-start;
		text-align: left;
		font-weight: 400;
		padding: 4px 6px;
		border-radius: 16px;
		gap: 2px;
	}
	.title {
		font-weight: 700;
		color: var(--ink-strong);
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.unread .title i {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #c2334f;
		display: inline-block;
	}
</style>
