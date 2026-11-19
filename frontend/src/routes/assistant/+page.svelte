<script lang="ts">
	import { AI_DOWN, api, apiRaw, softMessage } from '#lib/api.ts';
	import { child, refresh, toast } from '#lib/app.svelte.ts';
	import { fmtDay, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import Sheet from '#lib/Sheet.svelte';
	import { tick } from 'svelte';

	type Citation = { n: number; title: string; publisher: string; author?: string; url?: string; year?: number; kind: string; licence?: string };
	type Msg = { id?: number; role: 'user' | 'assistant'; content: string; citations: Citation[] };
	type Insight = { kind: string; severity: 'info' | 'attention' | 'urgent'; title: string; body: string; citations: Citation[] };

	let tab = $state<'ask' | 'insights' | 'plan' | 'milestones'>('ask');
	let source = $state<Citation | null>(null);

	// --- chat ---
	let messages = $state<Msg[]>([]);
	let question = $state('');
	let streaming = $state(false);
	let chatError = $state('');

	// --- insights, plan, milestones ---
	let insights = $state<Insight[] | null>(null);
	let insightsError = $state('');
	let plan = $state<any>(undefined);
	let planError = $state('');
	let planBusy = $state(false);
	let milestones = $state<any>(null);
	let msError = $state('');

	const cid = $derived(child()?.id);
	const ORDER = { urgent: 0, attention: 1, info: 2 };

	$effect(() => {
		if (!cid) return;
		api<Msg[]>(`/children/${cid}/assistant/messages`).then((m) => (messages = m)).catch((e) => (chatError = softMessage(e)));
		api<Insight[]>(`/children/${cid}/insights`)
			.then((r) => (insights = [...r].sort((a, b) => ORDER[a.severity] - ORDER[b.severity])))
			.catch((e) => (insightsError = softMessage(e, 'Insights are not available now.')));
		api(`/children/${cid}/sleep/plan`).then((p) => (plan = p)).catch((e) => ((plan = null), (planError = softMessage(e))));
		loadMilestones();
	});

	function loadMilestones() {
		api(`/children/${cid}/milestones`).then((m) => (milestones = m)).catch((e) => (msError = softMessage(e, 'Milestones are not available now.')));
	}

	async function ask(e: SubmitEvent) {
		e.preventDefault();
		const text = question.trim();
		if (!text || streaming) return;
		chatError = '';
		question = '';
		messages.push({ role: 'user', content: text, citations: [] });
		messages.push({ role: 'assistant', content: '', citations: [] });
		const answer = messages[messages.length - 1];
		streaming = true;
		// Show the new question at the top of the screen; the answer grows below it.
		tick().then(() => [...document.querySelectorAll('.msgs li.user')].at(-1)?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
		try {
			const res = await apiRaw(`/children/${cid}/assistant/chat`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
				body: JSON.stringify({ message: text })
			});
			if (!res.ok || !res.body) {
				const d = await res.json().catch(() => null);
				throw new Error(res.status === 503 && d?.detail ? d.detail : AI_DOWN);
			}
			const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
			let buf = '';
			for (;;) {
				const { value, done } = await reader.read();
				if (done) break;
				buf += value;
				let i;
				while ((i = buf.indexOf('\n\n')) >= 0) {
					const block = buf.slice(0, i);
					buf = buf.slice(i + 2);
					const ev = /^event: ?(.*)$/m.exec(block)?.[1].trim() ?? 'message';
					const data = JSON.parse(/^data: ?(.*)$/m.exec(block)?.[1] ?? '{}');
					if (ev === 'token') answer.content += data.text;
					else if (ev === 'citations') answer.citations = data.citations;
					else if (ev === 'done') answer.id = data.message_id;
					else if (ev === 'error') throw new Error(data.detail || AI_DOWN);
				}
			}
		} catch (err) {
			chatError = err instanceof TypeError ? AI_DOWN : (err as Error).message;
			if (!answer.content) messages.pop();
		} finally {
			streaming = false;
		}
	}

	async function clearChat() {
		await api(`/children/${cid}/assistant/messages`, { method: 'DELETE' }).catch(() => {});
		messages = [];
	}

	async function makePlan() {
		planBusy = true;
		planError = '';
		try {
			plan = await api(`/children/${cid}/sleep/plan`, { method: 'POST' });
		} catch (e) {
			planError = softMessage(e);
		} finally {
			planBusy = false;
		}
	}

	async function achieve(item: any) {
		try {
			await api(`/children/${cid}/entries`, { method: 'POST', body: { type: 'milestone', started_at: new Date().toISOString(), data: { key: item.key, title: item.text.slice(0, 100) } } });
			toast('Milestone saved');
			loadMilestones();
			refresh();
		} catch (e) {
			msError = (e as Error).message;
		}
	}

	/** Split "text [1] more" into text parts and citation numbers. */
	const pieces = (s: string) => s.split(/(\[\d+\])/).map((p) => (/^\[\d+\]$/.test(p) ? Number(p.slice(1, -1)) : p));
	const cite = (list: Citation[], n: number) => list.find((c) => c.n === n);
</script>

<svelte:head><title>Assistant · Frecklebubby</title></svelte:head>

{#snippet chips(list: Citation[])}
	{#if list.length}
		<div class="chips cites">
			{#each list as c (c.n)}
				<button class="cite" onclick={() => (source = c)}>[{c.n}] {c.publisher || c.title}</button>
			{/each}
		</div>
	{/if}
{/snippet}

<h1>Assistant</h1>
<div class="seg tabs" role="tablist" aria-label="Assistant sections">
	{#each [['ask', 'Ask'], ['insights', 'Insights'], ['plan', 'Sleep plan'], ['milestones', 'Milestones']] as [k, l] (k)}
		<button role="tab" aria-selected={tab === k} onclick={() => (tab = k as typeof tab)}>{l}</button>
	{/each}
</div>

{#if tab === 'ask'}
	<section class="card chat" aria-label="Chat">
		{#if !messages.length}
			<p class="muted">Ask about sleep, feeding or development. I use {child()?.name}'s logs and trusted sources.</p>
		{/if}
		<ul class="msgs" aria-live="polite">
			{#each messages as m, i (i)}
				<li class={m.role}>
					{#if m.role === 'assistant'}
						{@const live = streaming && i === messages.length - 1}
						{#each (m.content || (live ? '…' : '')).split(/\n\n+/) as para, k (k)}
							<p class:urgent={para.startsWith('Urgent:')}>
								{#each pieces(para) as p, j (j)}
									{#if typeof p === 'number' && cite(m.citations, p)}
										<button class="mark" onclick={() => (source = cite(m.citations, p as number)!)} aria-label="Source {p}">{p}</button>
									{:else if typeof p === 'number' && live}<span class="mark">{p}</span>
									{:else}{typeof p === 'number' ? `[${p}]` : p}{/if}
								{/each}
							</p>
						{/each}
						{@render chips(m.citations)}
					{:else}
						<p>{m.content}</p>
					{/if}
				</li>
			{/each}
		</ul>
		{#if chatError}<p class="error" role="alert">{chatError}</p>{/if}
		<form class="row ask" onsubmit={ask}>
			<label for="q" class="sr-only">Your question</label>
			<input id="q" placeholder="Ask a question…" bind:value={question} autocomplete="off" />
			<button class="icon send" type="submit" disabled={streaming || !question.trim()} aria-label="Send"><Icon name="send" /></button>
		</form>
		<div class="spread">
			<p class="disclaimer">General information, not medical advice.</p>
			{#if messages.length}<button class="plain small" onclick={clearChat}>Clear chat</button>{/if}
		</div>
	</section>
{:else if tab === 'insights'}
	<section aria-label="Insights">
		{#if insightsError}
			<p class="notice">{insightsError}</p>
		{:else if insights === null}
			<p class="empty">Loading…</p>
		{:else if !insights.length}
			<p class="empty card">No insights now. Keep logging and check again later.</p>
		{:else}
			{#each insights as c, i (i)}
				<article class="card insight {c.severity}">
					<p class="sev">{c.severity === 'urgent' ? 'Urgent' : c.severity === 'attention' ? 'Look at this' : 'For your information'}</p>
					<h2>{c.title}</h2>
					<p>{c.body}</p>
					{@render chips(c.citations)}
				</article>
			{/each}
		{/if}
		<p class="disclaimer">General information, not medical advice.</p>
	</section>
{:else if tab === 'plan'}
	<section class="card" aria-label="Sleep plan">
		{#if plan}
			<h2>Sleep plan</h2>
			<p class="muted small">Made {fmtDay(localDay(plan.created_at), { day: 'numeric', month: 'long' })}</p>
			<p>{plan.summary}</p>
			<ol class="schedule">
				{#each plan.schedule as row, i (i)}
					<li class={row.kind}><strong>{row.time}</strong><span>{row.label}{#if row.note}<br /><span class="muted small">{row.note}</span>{/if}</span></li>
				{/each}
			</ol>
			{#if plan.advice?.length}
				<h3>Advice</h3>
				<ul>
					{#each plan.advice as a, i (i)}
						<li>{a.text}{#each a.cites ?? [] as n (n)}{@const c = cite(plan.citations, n)}{#if c}<button class="mark" onclick={() => (source = c)} aria-label="Source {n}">{n}</button>{/if}{/each}</li>
					{/each}
				</ul>
			{/if}
			{@render chips(plan.citations ?? [])}
		{:else if plan === null && !planError}
			<p class="muted">No plan yet. The assistant can suggest a day plan from {child()?.name}'s recent sleep.</p>
		{/if}
		{#if planError}<p class="notice">{planError}</p>{/if}
		<button class="wide" disabled={planBusy || plan === undefined} onclick={makePlan}>
			<Icon name="sparkle" /> {planBusy ? 'Making the plan… this can take a minute' : plan ? 'Make a new plan' : 'Make a sleep plan'}
		</button>
		<p class="disclaimer">General information, not medical advice.</p>
	</section>
{:else}
	<section aria-label="Milestones">
		{#if msError}<p class="notice">{msError}</p>{/if}
		{#if milestones}
			<p class="muted small">Checklist from CDC "Learn the Signs. Act Early." Every child grows at their own pace.</p>
			{#each milestones.bands as band (band.age_months)}
				<details class="card band" open={band.age_months <= milestones.age_months + 2 && band.age_months >= milestones.age_months - 3}>
					<summary><h2>By {band.age_months} months</h2><span class="muted small">{band.items.filter((x: any) => x.achieved).length} of {band.items.length}</span></summary>
					<ul class="list">
						{#each band.items as item (item.key)}
							<li class="ms">
								{#if item.achieved}
									<span class="done" aria-label="Done"><Icon name="check" size={20} /></span>
								{:else}
									<button class="icon tick" aria-label="Mark done: {item.text}" onclick={() => achieve(item)}></button>
								{/if}
								<span>{item.text}<br /><span class="muted small dom">{item.domain}{item.achieved_at ? ` · ${fmtDay(localDay(item.achieved_at), { day: 'numeric', month: 'short' })}` : ''}</span></span>
							</li>
						{/each}
					</ul>
					<a class="small" href={band.items[0]?.source.url} target="_blank" rel="noopener">Source: {band.items[0]?.source.publisher}</a>
				</details>
			{/each}
		{:else if !msError}
			<p class="empty">Loading…</p>
		{/if}
	</section>
{/if}

{#if source}
	<Sheet title="Source" onclose={() => (source = null)}>
		<div class="stack">
			<h3>[{source.n}] {source.title}</h3>
			<p class="muted">
				{[source.author, source.publisher, source.year].filter(Boolean).join(' · ')}<br />
				{{ bundled: 'From the built-in library', link: 'Trusted source (link only)', upload: 'Your family upload', web: 'Read from an approved website' }[source.kind] ?? ''}
				{#if source.licence}· Licence: {source.licence}{/if}
			</p>
			{#if source.url}<a class="btn wide" href={source.url} target="_blank" rel="noopener"><Icon name="link" /> Open source</a>{/if}
		</div>
	</Sheet>
{/if}

<style>
	.tabs {
		margin-bottom: 14px;
	}
	.tabs button {
		font-size: 0.85rem;
		padding: 6px 4px;
	}
	.msgs {
		list-style: none;
		padding: 0;
		margin: 0 0 12px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.msgs li {
		max-width: 90%;
		padding: 10px 14px;
		border-radius: 20px;
	}
	.msgs li p {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.msgs li p + p {
		margin-top: 10px;
	}
	.msgs p.urgent {
		background: var(--danger-bg);
		color: var(--danger);
		border-left: 6px solid #c2334f;
		border-radius: 12px;
		padding: 8px 10px;
		font-weight: 700;
	}
	.msgs .user {
		align-self: flex-end;
		background: var(--lavender);
		color: var(--ink-strong);
		border-bottom-right-radius: 6px;
	}
	.msgs .assistant {
		align-self: flex-start;
		background: var(--cloud);
		border-bottom-left-radius: 6px;
	}
	.send {
		background: var(--lavender);
	}
	.ask input {
		border-radius: 999px;
	}
	.cites {
		margin-top: 8px;
		gap: 6px;
	}
	.cite {
		min-height: 36px;
		padding: 4px 12px;
		font-size: 0.85rem;
		background: var(--surface);
		border: 1.5px solid var(--line);
	}
	.mark {
		display: inline-block;
		border-radius: 999px;
		min-height: 24px;
		min-width: 24px;
		padding: 0 6px;
		margin: 0 2px;
		font-size: 0.75rem;
		vertical-align: super;
		background: var(--lavender);
	}
	.insight {
		border-left: 8px solid var(--sky);
	}
	.insight.attention {
		border-left-color: #e2a53a;
	}
	.insight.urgent {
		border: 3px solid #c2334f;
		border-left-width: 8px;
		background: var(--danger-bg);
		color: var(--danger);
	}
	.insight.urgent h2 {
		color: var(--danger);
	}
	.sev {
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-bottom: 2px;
	}
	.schedule {
		list-style: none;
		padding: 0;
		margin: 0 0 12px;
	}
	.schedule li {
		display: flex;
		gap: 14px;
		padding: 8px 12px;
		border-radius: 14px;
		margin-bottom: 6px;
		background: var(--cloud);
	}
	.schedule li.nap,
	.schedule li.bedtime {
		background: var(--lavender);
		color: var(--ink-strong);
	}
	.schedule li.feed {
		background: var(--rose);
		color: var(--ink-strong);
	}
	.schedule strong {
		width: 48px;
		flex: none;
		font-variant-numeric: tabular-nums;
	}
	.band summary {
		display: flex;
		justify-content: space-between;
		align-items: center;
		cursor: pointer;
		min-height: 44px;
		list-style: none;
	}
	.band summary h2 {
		margin: 0;
	}
	.ms {
		display: flex;
		gap: 12px;
		align-items: flex-start;
	}
	.tick {
		background: var(--surface);
		border: 2px solid var(--muted);
		width: 44px;
		height: 44px;
		border-radius: 12px;
	}
	.dom::first-letter {
		text-transform: uppercase;
	}
	.done {
		width: 44px;
		height: 44px;
		flex: none;
		display: grid;
		place-items: center;
		background: var(--mint);
		border-radius: 12px;
		color: var(--ink-strong);
	}
</style>
