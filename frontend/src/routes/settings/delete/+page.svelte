<script lang="ts">
	// M16: delete the family (owner) or the account. Both are permanent.
	import { api, openClerkAccount } from '#lib/api.ts';
	import { app, loadMe } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import Icon from '#lib/Icon.svelte';

	const family = $derived(app.me?.family ?? null);
	const owner = $derived(app.me?.role === 'owner');
	let familyName = $state('');
	type Kid = { id: number; name: string; archived: boolean };
	let kids = $state<Kid[]>([]);
	let kidId = $state<number | null>(null);
	let kidName = $state('');
	const kid = $derived(kids.find((c) => c.id === kidId) ?? null);
	let email = $state('');
	let error = $state('');
	let busy = $state(false);

	async function remove(path: string, confirm: string) {
		busy = true;
		error = '';
		try {
			await api(path, { method: 'DELETE', body: { confirm } });
			localStorage.removeItem('fb.child');
			location.href = '/';
		} catch (e) {
			error = (e as Error).message;
			busy = false;
		}
	}
	const deleteChild = (e: SubmitEvent) => (e.preventDefault(), remove(`/children/${kidId}/permanent`, kidName));
	const deleteFamily = (e: SubmitEvent) => (e.preventDefault(), remove('/family', familyName));
	const deleteAccount = (e: SubmitEvent) => (e.preventDefault(), remove('/me', email));
	$effect(() => void loadMe());
	$effect(() => {
		if (family) api<Kid[]>('/children?archived=true').then((list) => (kids = list)).catch(() => {});
	});
</script>

<Back title="Delete data" />
<p class="muted">Deletion is permanent. You cannot undo it. To keep a copy, download the CSV export of each child first (on the Reports page).</p>
{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if family && owner && kids.length}
	<form class="card stack" onsubmit={deleteChild} aria-label="Delete a child">
		<h2>Delete a child</h2>
		<p>This deletes one child and all the data of that child: entries, timers, reminders, notifications, chats, the sleep plan and the support report. The family and the other children stay. To hide a child and keep the data, archive the child (Settings › Children).</p>
		<label class="field"><span>Child</span>
			<select bind:value={kidId} onchange={() => (kidName = '')} required>
				<option value={null} disabled>Select a child</option>
				{#each kids as c (c.id)}<option value={c.id}>{c.name}{c.archived ? ' (archived)' : ''}</option>{/each}
			</select></label>
		{#if kid}
			<label class="field"><span>Type the child's name to confirm: <strong>{kid.name}</strong></span>
				<input bind:value={kidName} autocomplete="off" required /></label>
		{/if}
		<button type="submit" class="danger" disabled={busy || !kid || kidName.trim().toLowerCase() !== kid.name.trim().toLowerCase()}>
			<Icon name="trash" size={20} /> Delete the child for good</button>
	</form>
{:else if family && kids.length}
	<p class="card muted">Only the family owner can delete a child.</p>
{/if}

{#if family && owner}
	<form class="card stack" onsubmit={deleteFamily} aria-label="Delete the family">
		<h2>Delete the family</h2>
		<p>This deletes {family.name} and all its data: children, entries, timers, reminders, notifications, chats, sleep plans, support reports, uploaded files and imports. The carers stay as users without a family. Their API tokens and push messages stop.</p>
		{#if app.config?.invite_only}<p>After this you need a new invite to use this server again.</p>{/if}
		<label class="field"><span>Type the family name to confirm: <strong>{family.name}</strong></span>
			<input bind:value={familyName} autocomplete="off" required /></label>
		<button type="submit" class="danger" disabled={busy || familyName.trim().toLowerCase() !== family.name.trim().toLowerCase()}>
			<Icon name="trash" size={20} /> Delete the family for good</button>
	</form>
{:else if family}
	<p class="card muted">Only the family owner can delete the family.</p>
{/if}

<form class="card stack" onsubmit={deleteAccount} aria-label="Delete my account">
	<h2>Delete my account</h2>
	<p>This deletes your account here: your membership, API tokens and push messages. Entries you made stay in the family, without your name.</p>
	{#if family && owner}
		<p>You are the owner. If there are other carers, first make another carer the owner (Settings › Family and carers) or delete the family. If you are the only carer, this also deletes the family.</p>
	{/if}
	<label class="field"><span>Type your email to confirm: <strong>{app.me?.user.email}</strong></span>
		<input type="email" bind:value={email} autocomplete="off" required /></label>
	<button type="submit" class="danger" disabled={busy || email.trim().toLowerCase() !== app.me?.user.email}>
		<Icon name="trash" size={20} /> Delete my account for good</button>
</form>

<section class="card stack">
	<h2>Your sign-in account</h2>
	<p>You sign in with an account at Clerk. That account is separate from your data here, and deleting your data does not delete it. To delete it, open your Clerk account, go to Security and select Delete account.</p>
	{#if app.config?.auth_mode === 'clerk'}<button class="ghost" onclick={openClerkAccount}>Open my Clerk account</button>{/if}
</section>
