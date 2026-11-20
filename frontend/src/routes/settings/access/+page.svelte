<script lang="ts">
	// M17: Settings > Server access, for the operators in OPERATOR_EMAILS. No child data; no change to families.
	import { api } from '#lib/api.ts';
	import { toast } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import { fmtDay, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';

	type Invite = { id: number; email: string; created_at: string; used_at: string | null };
	type Family = { name: string; members: string[]; created_at: string; last_activity: string };
	let invites = $state<Invite[]>([]);
	let families = $state<Family[]>([]);
	let email = $state('');
	let error = $state('');

	const load = async () =>
		([invites, families] = await Promise.all([api<Invite[]>('/operator/invites'), api<Family[]>('/operator/families')]));
	$effect(() => void load().catch((e) => (error = e.message)));
	const day = (iso: string) => fmtDay(localDay(iso), { day: 'numeric', month: 'short', year: 'numeric' });

	async function run(fn: () => Promise<unknown>, msg: string) {
		error = '';
		try {
			await fn();
			toast(msg);
			await load();
		} catch (e) {
			error = (e as Error).message;
		}
	}
	const invite = (e: SubmitEvent) => (e.preventDefault(), run(async () => (await api('/operator/invites', { method: 'POST', body: { email } }), (email = '')), 'Invite saved'));
	const drop = (i: Invite) => run(() => api(`/operator/invites/${i.id}`, { method: 'DELETE' }), 'Invite removed');
</script>

<Back title="Server access" />
<p class="muted">This server is invite only. An invited email can sign in and start one family. The app sends no email: tell the person yourself.</p>
{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="card stack">
	<h2>Invites</h2>
	<form class="stack" onsubmit={invite}>
		<label class="field"><span>Invite an email</span><input type="email" bind:value={email} required placeholder="name@example.com" /></label>
		<button type="submit">Invite</button>
	</form>
	{#if invites.length}
		<ul class="list" aria-label="Invites">
			{#each invites as i (i.id)}
				<li class="spread">
					<span class="who">{i.email}<span class="muted small">{i.used_at ? `Used ${day(i.used_at)}` : `Waiting since ${day(i.created_at)}`}</span></span>
					<button class="icon" aria-label="Remove invite for {i.email}" onclick={() => drop(i)}><Icon name="trash" size={20} /></button>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<section class="card stack">
	<h2>Families</h2>
	<p class="muted small">You see names and dates only. A family belongs to its owner: you cannot change or delete it.</p>
	{#if families.length}
		<ul class="list" aria-label="Families">
			{#each families as f, k (k)}
				<li class="who"><strong>{f.name}</strong><span class="muted small">{f.members.join(', ')}</span>
					<span class="muted small">Made {day(f.created_at)} · Last activity {day(f.last_activity)}</span></li>
			{/each}
		</ul>
	{:else}
		<p class="muted">No families yet.</p>
	{/if}
</section>

<style>
	.who {
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.who strong {
		color: var(--ink-strong);
	}
</style>
