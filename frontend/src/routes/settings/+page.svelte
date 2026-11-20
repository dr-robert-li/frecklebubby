<script lang="ts">
	import { signOut } from '#lib/api.ts';
	import { app } from '#lib/app.svelte.ts';
	import Icon from '#lib/Icon.svelte';

	const items = [
		['children', 'Children', 'Add, change or archive', 'nursing'],
		['family', 'Family and carers', 'Name, time zone, invites', 'home'],
		['units', 'Units and wording', 'ml or oz, kg or lb, nappy or diaper', 'growth'],
		['reminders', 'Reminders', 'Feeds, nappies, medicine, sleep', 'history'],
		['notifications', 'Notifications on this device', 'Push messages', 'bell'],
		['ai', 'AI model', 'Server, model and key', 'sparkle'],
		['knowledge', 'Knowledge sources', 'Library and your uploads', 'note'],
		['tokens', 'API tokens and MCP', 'Connect scripts and AI apps', 'link'],
		['import', 'Import from Huckleberry', 'Copy your old data once', 'download'],
		['appearance', 'Appearance', 'Night theme, clock', 'sun'],
		['delete', 'Delete data', 'The family or your account', 'trash']
	];
	const shown = $derived(app.me?.operator ? [['access', 'Server access', 'Invites and families', 'link'], ...items] : items);
</script>

<svelte:head><title>Settings · Frecklebubby</title></svelte:head>

<h1>Settings</h1>
<nav class="card menu" aria-label="Settings">
	{#each shown as [href, label, hint, icon] (href)}
		<a href="/settings/{href}">
			<span class="ic"><Icon name={icon} size={20} /></span>
			<span class="txt"><strong>{label}</strong><span class="muted small">{hint}</span></span>
			<Icon name="right" size={18} />
		</a>
	{/each}
</nav>
<p class="muted small center">Signed in as {app.me?.user.email} · Frecklebubby {app.config?.version}</p>
{#if app.config?.auth_mode === 'clerk'}<button class="ghost wide" onclick={signOut}>Sign out</button>{/if}

<style>
	.menu {
		padding: 6px;
	}
	.menu a {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px;
		min-height: 60px;
		border-radius: 18px;
		text-decoration: none;
		color: var(--ink);
		font-weight: 400;
	}
	.menu a:hover {
		background: var(--cloud);
	}
	.ic {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		background: var(--cloud);
		display: grid;
		place-items: center;
		flex: none;
		color: var(--ink-strong);
	}
	.txt {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.txt strong {
		color: var(--ink-strong);
	}
	.center {
		text-align: center;
		overflow-wrap: anywhere;
	}
</style>
