<script lang="ts">
	import { api } from '#lib/api.ts';
	import { app, toast } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';

	const supported = typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
	let subscribed = $state(false);
	let error = $state('');
	let busy = $state(false);
	let permission = $state(supported ? Notification.permission : 'denied');

	$effect(() => {
		if (!supported) return;
		navigator.serviceWorker.getRegistration().then((r) => r?.pushManager.getSubscription()).then((s) => (subscribed = !!s));
	});

	function key(b64: string) {
		const s = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
		return Uint8Array.from(s, (c) => c.charCodeAt(0));
	}

	async function run(fn: () => Promise<void>) {
		busy = true;
		error = '';
		try {
			await fn();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	const turnOn = () =>
		run(async () => {
			permission = await Notification.requestPermission();
			if (permission !== 'granted') throw new Error('Notifications are blocked. Allow them in your browser settings.');
			const reg = (await navigator.serviceWorker.getRegistration()) ?? (await navigator.serviceWorker.register('/sw.js'));
			await navigator.serviceWorker.ready;
			const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key(app.config!.vapid_public_key) });
			await api('/push/subscriptions', { method: 'POST', body: sub.toJSON() });
			subscribed = true;
			toast('Notifications on');
		});

	const turnOff = () =>
		run(async () => {
			const sub = await (await navigator.serviceWorker.getRegistration())?.pushManager.getSubscription();
			if (sub) {
				await api('/push/subscriptions', { method: 'DELETE', body: { endpoint: sub.endpoint } });
				await sub.unsubscribe();
			}
			subscribed = false;
			toast('Notifications off');
		});

	const test = () =>
		run(async () => {
			const r = await api<{ sent: number }>('/push/test', { method: 'POST' });
			toast(r.sent ? `Test sent to ${r.sent} device${r.sent === 1 ? '' : 's'}` : 'No device has notifications on');
		});
</script>

<Back title="Notifications on this device" />

<section class="card stack">
	{#if !supported}
		<p class="notice">This browser cannot show push notifications. On iPhone, add Frecklebubby to the Home Screen first. Push also needs HTTPS.</p>
	{:else}
		<p>Get reminders on this device, also when the app is closed.</p>
		<p class="muted small">Status: {subscribed ? 'On' : permission === 'denied' ? 'Blocked in browser settings' : 'Off'}</p>
		{#if subscribed}
			<button class="ghost wide" disabled={busy} onclick={turnOff}>Turn off on this device</button>
		{:else}
			<button class="wide" disabled={busy} onclick={turnOn}>Turn on notifications</button>
		{/if}
	{/if}
	<button class="ghost wide" disabled={busy} onclick={test}>Send test notification</button>
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	<p class="muted small">See all messages on the <a href="/notifications">notifications page</a>.</p>
</section>
