<script lang="ts">
	import { api, softMessage } from '#lib/api.ts';
	import { toast } from '#lib/app.svelte.ts';
	import Back from '#lib/Back.svelte';
	import Icon from '#lib/Icon.svelte';

	type Source = { id: number; kind: string; title: string; author: string | null; publisher: string | null; url: string | null; year: number | null; own: boolean };
	let sources = $state<Source[] | null>(null);
	let error = $state('');
	let busy = $state(false);
	let input: HTMLInputElement;
	const KINDS = [['upload', 'Your uploads'], ['bundled', 'Built-in library'], ['link', 'Trusted sources (links)'], ['web', 'Read from approved websites']];

	const load = () => api<Source[]>('/knowledge/sources').then((s) => (sources = s)).catch((e) => ((sources = []), (error = softMessage(e, 'Knowledge sources are not available now.'))));
	$effect(() => void load());

	async function upload() {
		const file = input.files?.[0];
		if (!file) return;
		error = '';
		if (file.size > 50 * 1024 * 1024) return void (error = 'The file is too big. The limit is 50 MB.');
		busy = true;
		const form = new FormData();
		form.append('file', file);
		try {
			const r = await api<{ title: string; chunks: number }>('/knowledge/uploads', { method: 'POST', form });
			toast(`Added "${r.title}" (${r.chunks} ${r.chunks === 1 ? "part" : "parts"})`);
			load();
		} catch (e) {
			error = softMessage(e, 'Uploads are not available now.');
		} finally {
			busy = false;
			input.value = '';
		}
	}

	async function remove(s: Source) {
		await api(`/knowledge/sources/${s.id}`, { method: 'DELETE' }).catch((e) => (error = e.message));
		toast('Source deleted');
		load();
	}
</script>

<Back title="Knowledge sources" />
<p class="muted">The assistant answers from these sources and shows which ones it used.</p>

<section class="card stack">
	<h2>Add your own</h2>
	<p class="muted small">PDF, EPUB, text or Markdown, up to 50 MB. Only your family can use it.</p>
	<label class="btn ghost wide upload">
		<Icon name="upload" /> {busy ? 'Uploading…' : 'Choose a file'}
		<input bind:this={input} type="file" accept=".pdf,.epub,.txt,.md,application/pdf,application/epub+zip,text/plain,text/markdown" onchange={upload} disabled={busy} class="sr-only" />
	</label>
	{#if error}<p class="notice" role="alert">{error}</p>{/if}
</section>

{#if sources}
	{#each KINDS as [kind, label] (kind)}
		{@const list = sources.filter((s) => s.kind === kind)}
		{#if list.length}
			<section class="card">
				<h2>{label} <span class="muted small">({list.length})</span></h2>
				<ul class="list">
					{#each list as s (s.id)}
						<li class="spread">
							<span class="src"><strong>{s.title}</strong>
								<span class="muted small">{[s.author, s.publisher, s.year].filter(Boolean).join(' · ')}</span>
								{#if s.url}<a class="small" href={s.url} target="_blank" rel="noopener">Open</a>{/if}</span>
							{#if s.own}<button class="icon" aria-label="Delete {s.title}" onclick={() => remove(s)}><Icon name="trash" size={20} /></button>{/if}
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/each}
{:else}
	<p class="empty">Loading…</p>
{/if}

<style>
	.upload {
		cursor: pointer;
	}
	.upload:focus-within {
		outline: 3px solid var(--accent);
	}
	.src {
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.src strong {
		color: var(--ink-strong);
	}
	.src a {
		align-self: flex-start;
		min-height: 32px;
		display: inline-flex;
		align-items: center;
	}
</style>
