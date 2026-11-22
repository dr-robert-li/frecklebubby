<script lang="ts">
	import '@fontsource/nunito/400.css';
	import '@fontsource/nunito/600.css';
	import '@fontsource/nunito/700.css';
	import '@fontsource/nunito/800.css';
	import '../app.css';
	import { dev } from '$app/env';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, ApiError, devUser, initAuth, mountSignIn, setDevUser, signOut } from '#lib/api.ts';
	import { app, child, loadMe, refresh, selectChild } from '#lib/app.svelte.ts';
	import { ageText, prefs } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import Sheet from '#lib/Sheet.svelte';
	import { applyTheme } from '#lib/theme.ts';
	import VoiceCard from '#lib/VoiceCard.svelte';

	let { children } = $props();
	let phase = $state<'loading' | 'signin' | 'ready' | 'refused' | 'error'>('loading');
	let error = $state('');
	let signInNode = $state<HTMLDivElement>();
	let switcher = $state(false);
	let devEdit = $state(false);
	let devEmail = $state(devUser());
	let dark = $state(false);
	// messages of a plug-in of this server, for the family owner: each shows one time
	let notices = $state<{ key: string; title: string; text: string }[]>([]);

	const tabs = [
		['/', 'Home', 'home'],
		['/history', 'History', 'history'],
		['/reports', 'Reports', 'reports'],
		['/assistant', 'Assistant', 'assistant'],
		['/settings', 'Settings', 'settings']
	];
	const onboarding = $derived(page.url.pathname.startsWith('/onboarding'));
	const active = (href: string) => (href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href));

	async function start() {
		dark = applyTheme();
		try {
			prefs.clock24 = localStorage.getItem('fb.clock') !== '12';
		} catch {
			/* default 24 h */
		}
		try {
			const { config, signedIn } = await initAuth();
			app.config = config;
			if (!signedIn) {
				phase = 'signin';
				return;
			}
			await loadMe();
			phase = 'ready';
			if (!app.me!.family || !app.me!.children.length) goto('/onboarding');
			else if (onboarding) goto('/');
			refresh();
			if (config.plugins && app.me!.role === 'owner')
				api<{ notices: typeof notices }>('/plugins').then((r) => (notices = r.notices), () => {});
		} catch (e) {
			error = (e as Error).message;
			phase = e instanceof ApiError && e.status === 403 ? 'refused' : 'error';
		}
	}

	$effect(() => {
		start();
		const tick = setInterval(() => (app.now = Date.now()), 1000);
		// shortcut: poll every 15 s for other carers' changes; move to SSE if the server load matters.
		const poll = setInterval(() => document.visibilityState === 'visible' && refresh(), 15000);
		const onFocus = () => refresh();
		window.addEventListener('focus', onFocus);
		document.addEventListener('visibilitychange', onFocus);
		if (!dev && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
		return () => {
			clearInterval(tick);
			clearInterval(poll);
			window.removeEventListener('focus', onFocus);
			document.removeEventListener('visibilitychange', onFocus);
		};
	});

	$effect(() => {
		if (phase === 'signin' && signInNode) mountSignIn(signInNode);
	});

	function seen() {
		const [n, ...rest] = notices;
		notices = rest;
		api(`/plugins/notices/${n.key}/seen`, { method: 'POST' }).catch(() => {});
	}

	function changeDevUser(e: SubmitEvent) {
		e.preventDefault();
		setDevUser(devEmail.trim());
		localStorage.removeItem('fb.child');
		location.href = '/';
	}
</script>

{#if app.config?.auth_mode === 'dev'}
	<div class="devbar">
		{#if devEdit}
			<form class="row" onsubmit={changeDevUser}>
				<label class="sr-only" for="dev-email">Development user email</label>
				<input id="dev-email" type="email" bind:value={devEmail} required />
				<button type="submit">Sign in</button>
			</form>
		{:else}
			<span class="who-dev">Dev sign-in: {devUser()}</span>
			<button class="plain" onclick={() => (devEdit = true)}>Change</button>
		{/if}
	</div>
{/if}

{#if phase === 'loading'}
	<p class="empty" aria-live="polite">Loading…</p>
{:else if phase === 'refused'}
	<!-- M17: an email with no way in. No retry: it gives the same answer. -->
	<main><div class="card stack"><h1>No access</h1><p>{error}</p>
		{#if app.config?.auth_mode === 'clerk'}<button onclick={signOut}>Sign out</button>{/if}</div></main>
{:else if phase === 'error'}
	<main><div class="card"><h1>Cannot load Frecklebubby</h1><p class="error">{error}</p><button onclick={() => location.reload()}>Try again</button></div></main>
{:else if phase === 'signin'}
	<main class="signin">
		<img src="/icon.svg" alt="" width="96" height="96" />
		<h1>Frecklebubby</h1>
		<p class="muted">Sign in to see your family.</p>
		<div bind:this={signInNode}></div>
	</main>
{:else}
	{#if !onboarding && app.me?.family}
		{@const c = child()}
		<header>
			<a class="brand" href="/"><img src="/icon.svg" alt="" width="34" height="34" /> Frecklebubby</a>
			<button class="bell theme" onclick={() => (dark = applyTheme(dark ? 'light' : 'dark'))} aria-label={dark ? 'Change to day colours' : 'Change to night colours'}>
				<Icon name={dark ? 'sun' : 'moon'} />
			</button>
			<a class="bell" href="/notifications" aria-label="Notifications{app.status?.unread_notifications ? `, ${app.status.unread_notifications} unread` : ''}">
				<Icon name="bell" />
				{#if app.status?.unread_notifications}<span class="badge">{app.status.unread_notifications}</span>{/if}
			</a>
			{#if c}
				<div class="child-row">
					<button class="who" onclick={() => (switcher = true)} aria-label="Child: {c.name}. Change child">
						<span class="dot" style="background:{c.color}"></span>
						<span class="name">{c.name}</span>
						<span class="muted small age">{ageText(c.birthdate)}</span>
						{#if app.me.children.length > 1}<Icon name="down" size={18} />{/if}
					</button>
				</div>
			{/if}
		</header>
	{/if}

	<main class:withtabs={!onboarding}>
		{@render children()}
	</main>

	{#if !onboarding && app.me?.family}<VoiceCard />{/if}

	{#if notices.length && !onboarding}
		<Sheet title={notices[0].title} onclose={seen}>
			<p class="notice-text">{notices[0].text}</p>
			<button class="wide" onclick={seen}>OK</button>
		</Sheet>
	{/if}

	{#if !onboarding}
		<nav aria-label="Main">
			{#each tabs as [href, label, icon] (href)}
				<a {href} aria-current={active(href) ? 'page' : undefined}><Icon name={icon} /><span>{label}</span></a>
			{/each}
		</nav>
	{/if}
{/if}

{#if switcher && app.me}
	<Sheet title="Choose a child" onclose={() => (switcher = false)}>
		<ul class="list">
			{#each app.me.children as c (c.id)}
				<li>
					<button class="pick" aria-pressed={c.id === app.childId} onclick={() => (selectChild(c.id), (switcher = false))}>
						<span class="dot" style="background:{c.color}"></span>{c.name}
						<span class="muted small">{ageText(c.birthdate)}</span>
					</button>
				</li>
			{/each}
		</ul>
		<a class="btn ghost" href="/settings/children" onclick={() => (switcher = false)}><Icon name="plus" /> Add a child</a>
	</Sheet>
{/if}

<div class="toast" role="status" aria-live="polite">
	{#if app.toast}<span>{app.toast}</span>{/if}
</div>

<style>
	.notice-text {
		white-space: pre-line;
		margin: 0 0 16px;
	}
	main {
		max-width: 520px;
		margin: 0 auto;
		padding: 8px 16px 24px;
	}
	main.withtabs {
		padding-bottom: calc(100px + env(safe-area-inset-bottom));
	}
	.devbar {
		background: var(--butter);
		color: var(--ink-strong);
		font-size: 0.85rem;
		font-weight: 700;
		padding: 0 8px 0 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		min-height: 36px;
	}
	.who-dev {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.devbar .plain {
		flex: none;
		min-height: 36px;
		color: var(--ink-strong);
		text-decoration: underline;
	}
	.devbar input {
		min-height: 40px;
		padding: 6px 10px;
	}
	.devbar form button {
		min-height: 40px;
	}
	header {
		max-width: 520px;
		margin: 0 auto;
		padding: 12px 16px 4px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 8px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 1.3rem;
		font-weight: 800;
		color: var(--ink-strong);
		text-decoration: none;
	}
	.child-row {
		flex-basis: 100%;
		display: flex;
		min-width: 0;
	}
	.who {
		background: var(--surface);
		box-shadow: var(--shadow);
		padding: 6px 16px 6px 8px;
		min-width: 0;
		color: var(--ink-strong);
	}
	.who .name {
		font-size: 1.1rem;
		font-weight: 800;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.who .age {
		font-weight: 600;
		white-space: nowrap;
	}
	.dot {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		flex: none;
		border: 2px solid var(--surface);
		box-shadow: 0 0 0 1px var(--line);
	}
	.bell {
		position: relative;
		width: 48px;
		height: 48px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--surface);
		box-shadow: var(--shadow);
		color: var(--ink-strong);
		flex: none;
	}
	.bell.theme {
		margin-left: auto;
		padding: 0;
	}
	.bell .badge {
		position: absolute;
		top: -2px;
		right: -2px;
	}
	nav {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 10;
		display: flex;
		justify-content: center;
		background: var(--surface);
		box-shadow: 0 -4px 20px rgba(74, 68, 88, 0.1);
		border-radius: 24px 24px 0 0;
		padding: 6px 8px calc(6px + env(safe-area-inset-bottom));
	}
	nav a {
		flex: 1;
		max-width: 104px;
		min-height: 56px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.75rem;
		font-weight: 700;
		border-radius: 18px;
	}
	nav a[aria-current='page'] {
		color: var(--ink-strong);
		background: var(--lavender);
	}
	.signin {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		padding-top: 48px;
	}
	.pick {
		width: 100%;
		justify-content: flex-start;
		background: transparent;
		color: var(--ink-strong);
	}
	.pick[aria-pressed='true'] {
		background: var(--cloud);
	}
	.toast {
		position: fixed;
		left: 0;
		right: 0;
		bottom: calc(88px + env(safe-area-inset-bottom));
		display: flex;
		justify-content: center;
		pointer-events: none;
		z-index: 20;
	}
	.toast span {
		background: var(--ink-strong);
		color: var(--surface);
		padding: 10px 20px;
		border-radius: 999px;
		font-weight: 700;
		box-shadow: var(--shadow);
	}
</style>
