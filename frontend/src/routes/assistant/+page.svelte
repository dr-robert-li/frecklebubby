<script lang="ts">
	import { api, runJob, softMessage } from '#lib/api.ts';
	import { streamChat, type Item, type Msg } from '#lib/chat.ts';
	import { canVoice, onCommand } from '#lib/voice.svelte.ts';
	import VoiceButtons from '#lib/VoiceButtons.svelte';
	import { child, refresh, toast, wording } from '#lib/app.svelte.ts';
	import { fmtDay, localDay } from '#lib/format.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import Cites from '#lib/Cites.svelte';
	import SourceSheet, { type Citation } from '#lib/SourceSheet.svelte';
	import EntrySheet from '#lib/EntrySheet.svelte';
	import Proposals, { type Proposal } from '#lib/Proposals.svelte';
	import { tracker, type Entry } from '#lib/trackers.ts';
	import { tick } from 'svelte';

	type Insight = { kind: string; severity: 'info' | 'attention' | 'urgent'; title: string; body: string; citations: Citation[] };

	let tab = $state<'ask' | 'insights' | 'plan' | 'milestones'>('ask');
	let source = $state<Citation | null>(null);

	// --- chat ---
	let messages = $state<Msg[]>([]);
	let question = $state('');
	let streaming = $state(false);
	let asked = false; // a message was sent since the history request
	let chatError = $state('');
	let sheet = $state<{ type: Entry['type']; entry: Entry } | null>(null);
	let busyMsg = $state<number | null>(null);

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
		// A question sent before the history arrives must not be lost: keep the local turns then.
		asked = false;
		api<Msg[]>(`/children/${cid}/assistant/messages`).then((m) => void (asked || (messages = m))).catch((e) => (chatError = softMessage(e)));
		api<Insight[]>(`/children/${cid}/insights`)
			.then((r) => (insights = [...r].sort((a, b) => ORDER[a.severity] - ORDER[b.severity])))
			.catch((e) => (insightsError = softMessage(e, 'Insights are not available now.')));
		api(`/children/${cid}/sleep/plan`).then((p) => (plan = p)).catch((e) => ((plan = null), (planError = softMessage(e))));
		loadMilestones();
	});

	function loadMilestones() {
		api(`/children/${cid}/milestones`).then((m) => (milestones = m)).catch((e) => (msError = softMessage(e, 'Milestones are not available now.')));
	}

	function ask(e: SubmitEvent) {
		e.preventDefault();
		const text = question.trim();
		if (!text || streaming) return;
		question = '';
		send(text);
	}

	/** One chat turn. `voice`: a voice command (saves also what is not sure). Returns the answer, or null. */
	async function send(text: string, voice = false): Promise<Msg | null> {
		tab = 'ask';
		chatError = '';
		asked = true;
		messages.push({ role: 'user', content: text, citations: [] });
		messages.push({ role: 'assistant', content: '', citations: [] });
		const answer = messages[messages.length - 1];
		streaming = true;
		// Show the new question at the top of the screen; the answer grows below it.
		tick().then(() => [...document.querySelectorAll('.msgs li.user')].at(-1)?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
		try {
			await streamChat(cid!, text, answer, voice);
			return answer;
		} catch (err) {
			chatError = (err as Error).message;
			if (!answer.content && !answer.logged) messages.pop();
			return null;
		} finally {
			streaming = false;
		}
	}
	// Voice commands on this page go into the chat.
	$effect(() => onCommand((text) => send(text, true)));

	const canUndo = (it: Item) =>
		!!it.entry_id || ['start', 'pause', 'resume'].includes(it.timer_action ?? '') || (it.timer_action === 'switch' && it.type === 'nursing');

	async function undo(m: Msg, k: number) {
		busyMsg = m.id!;
		try {
			const r = await api<Msg>(`/children/${cid}/assistant/messages/${m.id}/undo`, { method: 'POST', body: { item: k } });
			m.logged = r.logged;
			toast('Undone');
			refresh();
		} catch (e) {
			chatError = softMessage(e);
		} finally {
			busyMsg = null;
		}
	}

	async function saveProposals(m: Msg, proposals: Proposal[]) {
		busyMsg = m.id!;
		try {
			const r = await api<Msg>(`/children/${cid}/assistant/messages/${m.id}/proposals`, { method: 'POST', body: { proposals } });
			m.logged = r.logged;
			if (proposals.length) toast(proposals.length === 1 ? 'Saved 1 item' : `Saved ${proposals.length} items`);
			refresh();
		} catch (e) {
			chatError = softMessage(e);
		} finally {
			busyMsg = null;
		}
	}

	async function edit(it: Item) {
		try {
			const entry = await api<Entry>(`/entries/${it.entry_id}`);
			sheet = { type: entry.type, entry };
		} catch (e) {
			chatError = softMessage(e);
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
			plan = await runJob(`/children/${cid}/sleep/plan`);
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
	<Cites {list} />
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
			<p class="muted">Ask about sleep, feeding or development. I use {child()?.name}'s logs and trusted sources. You can also tell me what happened, for example "120 ml formula at 2", and I log it.</p>
		{/if}
		<ul class="msgs" aria-live="polite" aria-busy={streaming}>
			{#each messages as m, i (i)}
				<li class={m.role}>
					{#if m.role === 'assistant'}
						{@const live = streaming && i === messages.length - 1}
						{#if m.logged?.items.length}
							<div class="logged" role="group" aria-label="Logged">
								<p class="lh"><Icon name="check" size={18} /> Logged</p>
								<ul>
									{#each m.logged.items as it, k (k)}
										<!-- An item saved before 0.2.2 can name a removed type (play, bath). -->
										{@const t = tracker(it.type, wording()) ?? tracker('activity', wording())}
										<li class:undone={it.undone}>
											<span class="bubble" style="background: var({t.color})"><Icon name={t.icon ?? t.type} size={18} /></span>
											<span class="what">{it.summary}{#if it.unsure && !it.undone}<br /><span class="unsure small">Not sure: {it.unsure}</span>{/if}</span>
											{#if it.undone}<span class="tag small">Undone</span>{/if}
											{#if !it.undone}
												{#if it.entry_id}<button class="ghost small" aria-label="Edit {it.summary}" onclick={() => edit(it)}>Edit</button>{/if}
												{#if canUndo(it)}<button class="ghost small" aria-label="Undo {it.summary}" disabled={busyMsg === m.id} onclick={() => undo(m, k)}>Undo</button>{/if}
											{/if}
										</li>
									{/each}
								</ul>
							</div>
						{/if}
						{#if m.logged?.proposals.length}
							<Proposals bind:proposals={m.logged.proposals} message={m.logged.message} busy={busyMsg === m.id} oncancel={() => saveProposals(m, [])} onsave={() => saveProposals(m, m.logged!.proposals)} />
						{/if}
						{#if live && m.waiting}<p class="muted" role="status">Waiting for the assistant…</p>{/if}
						{#each (m.content || (live && !m.logged && !m.waiting ? '…' : '')).split(/\n\n+/).filter(Boolean) as para, k (k)}
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
			<input id="q" placeholder={canVoice() ? 'Ask or tell me…' : 'Ask, or tell me what happened…'} bind:value={question} autocomplete="off" />
			<button class="icon send" type="submit" disabled={streaming || !question.trim()} aria-label="Send"><Icon name="send" /></button>
			<VoiceButtons />
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
			<p class="muted small">Checklist from CDC "Learn the Signs. Act Early." Every child grows at their own pace.{#if milestones.corrected} The bands use the corrected age ({milestones.age_months} months from the due date), as the NHS and the AAP advise until 2 years.{/if}</p>
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

{#if source}<SourceSheet {source} onclose={() => (source = null)} />{/if}
{#if sheet && cid}<EntrySheet type={sheet.type} entry={sheet.entry} childId={cid} onclose={() => (sheet = null)} />{/if}

<style>
	.unsure {
		color: var(--danger);
		font-weight: 700;
	}
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
	.logged {
		background: var(--surface);
		border-radius: 16px;
		padding: 8px 10px;
		margin-bottom: 8px;
	}
	.logged .lh {
		display: flex;
		gap: 6px;
		align-items: center;
		font-weight: 800;
		color: var(--ink-strong);
	}
	.logged ul {
		list-style: none;
		margin: 6px 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.logged li {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.logged li.undone .what {
		text-decoration: line-through;
		color: var(--muted);
	}
	.logged .tag {
		font-weight: 700;
		color: var(--muted);
	}
	.logged .what {
		flex: 1;
		min-width: 140px;
		font-size: 0.95rem;
	}
	.logged .bubble {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		flex: none;
		display: grid;
		place-items: center;
		color: var(--ink-strong);
	}
	.logged button {
		min-height: 44px;
		padding: 4px 12px;
	}
	.ask input {
		border-radius: 999px;
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
	.insight > p:not(.sev) {
		white-space: pre-line; /* development cards: one line per item */
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
