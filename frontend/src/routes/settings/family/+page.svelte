<script lang="ts">
	import { api } from '#lib/api.ts';
	import { app, loadMe, toast } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import Icon from '#lib/Icon.svelte';

	type Member = { user_id: number; email: string; name: string; role: string };
	type Invite = { id: number; email: string };
	const zones = Intl.supportedValuesOf('timeZone');
	let name = $state(app.me?.family?.name ?? '');
	let timezone = $state(app.me?.family?.timezone ?? '');
	let members = $state<Member[]>([]);
	let invites = $state<Invite[]>([]);
	let email = $state('');
	let error = $state('');
	const owner = $derived(app.me?.role === 'owner');

	const load = async () => ([members, invites] = await Promise.all([api<Member[]>('/family/members'), api<Invite[]>('/family/invites')]));
	$effect(() => void load());

	async function run(fn: () => Promise<unknown>, msg: string) {
		error = '';
		try {
			await fn();
			toast(msg);
		} catch (e) {
			error = (e as Error).message;
		}
	}
	const saveFamily = (e: SubmitEvent) => (e.preventDefault(), run(async () => (await api('/family', { method: 'PATCH', body: { name, timezone } }), await loadMe()), 'Family saved'));
	const invite = (e: SubmitEvent) => (e.preventDefault(), run(async () => (await api('/family/invites', { method: 'POST', body: { email } }), (email = ''), await load()), 'Invite saved'));
	const dropInvite = (i: Invite) => run(async () => (await api(`/family/invites/${i.id}`, { method: 'DELETE' }), await load()), 'Invite removed');
	const makeOwner = (m: Member) => run(async () => (await api(`/family/members/${m.user_id}/owner`, { method: 'POST' }), await loadMe(), await load()), `${m.email} is now the owner`);
	const dropMember = (m: Member) => run(async () => (await api(`/family/members/${m.user_id}`, { method: 'DELETE' }), await load()), `${m.email} removed`);
</script>

<Back title="Family and carers" />
{#if error}<p class="error" role="alert">{error}</p>{/if}

<form class="card stack" onsubmit={saveFamily}>
	<label class="field"><span>Family name</span><input bind:value={name} required maxlength="100" /></label>
	<label class="field"><span>Time zone</span>
		<select bind:value={timezone}>{#each zones as z (z)}<option value={z}>{z.replaceAll('_', ' ')}</option>{/each}</select></label>
	<button type="submit">Save</button>
</form>

<section class="card">
	<h2>Carers</h2>
	<ul class="list">
		{#each members as m (m.user_id)}
			<li class="spread">
				<span class="who"><strong>{m.name || m.email}</strong><span class="muted small">{m.email} · {m.role === 'owner' ? 'Owner' : 'Carer'}</span></span>
				{#if owner && m.role !== 'owner'}<span class="row"><button class="ghost small" aria-label="Make {m.email} the owner" onclick={() => makeOwner(m)}>Make owner</button>
					<button class="icon" aria-label="Remove {m.email}" onclick={() => dropMember(m)}><Icon name="trash" size={20} /></button></span>{/if}
			</li>
		{/each}
	</ul>
</section>

<section class="card">
	<h2>Invites</h2>
	{#if invites.length}
		<ul class="list">
			{#each invites as i (i.id)}
				<li class="spread"><span class="who">{i.email}<span class="muted small">Waiting for first sign-in</span></span>
					{#if owner}<button class="icon" aria-label="Remove invite for {i.email}" onclick={() => dropInvite(i)}><Icon name="trash" size={20} /></button>{/if}</li>
			{/each}
		</ul>
	{/if}
	{#if owner}
		<form class="stack" onsubmit={invite}>
			<label class="field"><span>Invite a carer by email</span><input type="email" bind:value={email} required placeholder="name@example.com" /></label>
			<p class="muted small">When they sign in with this email, they join your family.</p>
			<button type="submit">Invite</button>
		</form>
	{:else}
		<p class="muted small">Only the family owner can invite carers.</p>
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
