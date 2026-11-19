<script lang="ts">
	import { api, softMessage } from '#lib/api.ts';
	import { app, toast, type Settings } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';

	let baseUrl = $state(app.settings?.llm.base_url ?? '');
	let model = $state(app.settings?.llm.model ?? '');
	let key = $state('');
	let clearKey = $state(false);
	let error = $state('');
	let result = $state<{ ok: boolean; detail: string; model?: string } | null>(null);
	let testing = $state(false);

	async function save(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		const llm: Record<string, string | null> = { base_url: baseUrl.trim(), model: model.trim() };
		if (key) llm.api_key = key;
		else if (clearKey) llm.api_key = null;
		try {
			app.settings = await api<Settings>('/family/settings', { method: 'PATCH', body: { llm } });
			key = '';
			clearKey = false;
			toast('AI settings saved');
		} catch (err) {
			error = (err as Error).message;
		}
	}

	async function webLookup(on: boolean) {
		try {
			app.settings = await api<Settings>('/family/settings', { method: 'PATCH', body: { web_lookup: on } });
		} catch (err) {
			error = (err as Error).message;
		}
	}

	async function test() {
		testing = true;
		result = null;
		try {
			result = await api('/family/settings/llm-test', { method: 'POST' });
		} catch (err) {
			result = { ok: false, detail: softMessage(err, 'The test is not available on this server yet.') };
		} finally {
			testing = false;
		}
	}
</script>

<Back title="AI model" />
<p class="muted">The assistant uses an OpenAI-compatible server. The bundled llama.cpp server works without changes.</p>

<form class="card stack" onsubmit={save}>
	<label class="field"><span>Server URL</span><input type="url" bind:value={baseUrl} required placeholder="http://llama:8080/v1" /></label>
	<label class="field"><span>Model</span><input bind:value={model} /></label>
	<label class="field"><span>API key {app.settings?.llm.has_api_key ? '(saved, type to replace)' : '(optional)'}</span>
		<input type="password" bind:value={key} autocomplete="off" /></label>
	{#if app.settings?.llm.has_api_key}
		<label class="check"><input type="checkbox" bind:checked={clearKey} /> Remove the saved key</label>
	{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	<button type="submit" class="wide">Save</button>
	<button type="button" class="ghost wide" disabled={testing} onclick={test}>{testing ? 'Testing…' : 'Test connection'}</button>
	{#if result}
		<p class={result.ok ? 'notice ok' : 'error'} role="status">{result.ok ? 'Connected.' : 'Not connected.'} {result.detail}{result.model ? ` Model: ${result.model}` : ''}</p>
	{/if}
</form>

<section class="card">
	<label class="check"><input type="checkbox" checked={app.settings?.web_lookup} onchange={(e) => webLookup(e.currentTarget.checked)} />
		Look up approved medical websites for answers</label>
	<p class="muted small">Only sites on the approved list, such as health departments and children's hospitals.</p>
</section>

<style>
	.check {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 48px;
		font-weight: 700;
	}
	.ok {
		background: var(--mint);
	}
</style>
