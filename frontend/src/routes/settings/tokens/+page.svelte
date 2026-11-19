<script lang="ts">
	import { api } from '#lib/api.ts';
	import { toast } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import { fmtDay, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';

	type Token = { id: number; name: string; last_used_at: string | null; created_at: string };
	let tokens = $state<Token[]>([]);
	let name = $state('');
	let created = $state('');
	let error = $state('');
	const origin = typeof location !== 'undefined' ? location.origin : '';

	const load = async () => (tokens = await api<Token[]>('/tokens'));
	$effect(() => void load());

	async function create(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		try {
			const t = await api<Token & { token: string }>('/tokens', { method: 'POST', body: { name } });
			created = t.token;
			name = '';
			load();
		} catch (err) {
			error = (err as Error).message;
		}
	}
	async function remove(t: Token) {
		await api(`/tokens/${t.id}`, { method: 'DELETE' }).catch((e) => (error = e.message));
		toast('Token deleted');
		load();
	}
	async function copy(text: string) {
		await navigator.clipboard?.writeText(text).then(() => toast('Copied'), () => {});
	}
	const day = (iso: string) => fmtDay(localDay(iso), { day: 'numeric', month: 'short', year: 'numeric' });
</script>

<Back title="API tokens and MCP" />
<p class="muted">A token lets a script use the REST API as you. Keep it secret.</p>

<section class="card stack">
	<form class="stack" onsubmit={create}>
		<label class="field"><span>Name of the new token</span><input bind:value={name} required maxlength="100" placeholder="For example: Home Assistant" /></label>
		<button type="submit">Make token</button>
	</form>
	{#if created}
		<div class="notice stack" role="status">
			<strong>Copy this token now. You will not see it again.</strong>
			<code data-testid="new-token">{created}</code>
			<button class="ghost" onclick={() => copy(created)}>Copy</button>
		</div>
	{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if tokens.length}
		<ul class="list">
			{#each tokens as t (t.id)}
				<li class="spread">
					<span class="tok"><strong>{t.name}</strong><span class="muted small">Made {day(t.created_at)} · {t.last_used_at ? `last used ${day(t.last_used_at)}` : 'not used yet'}</span></span>
					<button class="icon" aria-label="Delete token {t.name}" onclick={() => remove(t)}><Icon name="trash" size={20} /></button>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<section class="card">
	<h2>REST API</h2>
	<p class="small">Send the token in the header <code>Authorization: Bearer fb_pat_…</code>. The API reference is at <a href="/api/docs" target="_blank" rel="noopener">/api/docs</a>.</p>
	<h2>MCP for AI apps</h2>
	<p class="small">Add this URL as a custom connector in Claude or another MCP client. You sign in with your Frecklebubby account.</p>
	<div class="row"><code class="url">{origin}/mcp</code><button class="ghost" onclick={() => copy(`${origin}/mcp`)}>Copy</button></div>
	<p class="muted small">The connector needs HTTPS. See the README for Tailscale Funnel or a reverse proxy.</p>
</section>

<style>
	code {
		background: var(--cloud);
		border-radius: 10px;
		padding: 2px 8px;
		overflow-wrap: anywhere;
		font-size: 0.85rem;
	}
	.notice code {
		background: var(--surface);
		padding: 10px;
		display: block;
	}
	.url {
		flex: 1;
		padding: 10px;
	}
	.tok {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.tok strong {
		color: var(--ink-strong);
	}
</style>
