<script lang="ts">
	// "Why is she crying?": listen for about 10 s (experimental), or check the logs only. Then save to the timeline.
	import { api, ApiError, apiRaw } from './api';
	import { child, refresh, toast, wording } from './app.svelte';
	import Cites from './Cites.svelte';
	import { toLocalInput } from './format.svelte';
	import Icon from './Icon.svelte';
	import Sheet from './Sheet.svelte';
	import type { Citation } from './SourceSheet.svelte';
	import { needLabel, soundLabel } from './trackers';

	type Need = { need: string; score: number; why: string; citations: Citation[] };
	type Result = {
		sound: { installed: boolean; is_cry: boolean; cry_seconds: number; snore_seconds: number; reasons: { label: string; probability: number }[]; experimental: true; reliability: string };
		likely_needs: Need[];
		suggestions: { kind: 'try' | 'help'; text: string; citations: Citation[] }[];
		urgent: { kind: string; severity: 'urgent' | 'attention' | 'info'; title: string; body: string; citations: Citation[] }[];
		combined: { need: string; why: string }[];
	};

	let { childId, onclose, onmanual }: { childId: number; onclose: () => void; onmanual: () => void } = $props();

	const SECONDS = 10;
	const opened = Date.now();
	let step = $state<'start' | 'listening' | 'busy' | 'result'>('start');
	let left = $state(SECONDS);
	let micError = $state('');
	let soundNote = $state(''); // sound analysis failed on the server; the logs still give a result
	let error = $state('');
	let result = $state<Result | null>(null);
	let listened = $state(false);
	let crying = $state('0');
	let helped = $state('');
	// the reason to save: the first of the list, until the parent selects another one
	let picked = $state<string | null>(null);
	const reason = $derived(picked ?? result?.combined[0]?.need ?? '');
	let saving = $state(false);
	let stopRec: (() => void) | null = null;
	const name = child()?.name ?? 'your baby';

	$effect(() => () => stopRec?.()); // release the microphone when the sheet closes

	function micProblem(): string {
		if (!window.isSecureContext)
			return 'The microphone works only on a secure (https) address. Ask the person who runs this server to set up HTTPS. You can still use "Just tell me what to check".';
		if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined')
			return 'This browser cannot record sound. You can still use "Just tell me what to check".';
		return '';
	}

	async function listen() {
		micError = micProblem();
		if (micError) return;
		let stream: MediaStream;
		try {
			stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch (e) {
			const n = (e as DOMException).name;
			micError =
				n === 'NotAllowedError' || n === 'SecurityError'
					? 'Microphone access is blocked. Allow the microphone for this site in the browser settings, then try again. Or use "Just tell me what to check".'
					: n === 'NotFoundError' || n === 'OverconstrainedError'
						? 'No microphone was found. Connect one and try again, or use "Just tell me what to check".'
						: 'The microphone did not start. Try again, or use "Just tell me what to check".';
			return;
		}
		const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find((t) => MediaRecorder.isTypeSupported(t));
		const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
		const parts: Blob[] = [];
		rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
		let timer: ReturnType<typeof setInterval>;
		const done = new Promise<void>((resolve) => (rec.onstop = () => resolve()));
		stopRec = () => {
			clearInterval(timer);
			if (rec.state !== 'inactive') rec.stop();
			stream.getTracks().forEach((t) => t.stop());
			stopRec = null;
		};
		left = SECONDS;
		step = 'listening';
		rec.start();
		timer = setInterval(() => {
			left -= 1;
			if (left <= 0) stopRec?.();
		}, 1000);
		await done;
		if (step !== 'listening') return; // cancelled
		const blob = new Blob(parts, { type: rec.mimeType || type || 'audio/webm' });
		await analyse(blob);
	}

	function cancelListen() {
		step = 'start';
		stopRec?.();
	}

	async function analyse(blob: Blob) {
		step = 'busy';
		listened = true;
		const form = new FormData();
		form.append('audio', blob, 'recording');
		try {
			const res = await apiRaw(`/children/${childId}/cry/analyze`, { method: 'POST', body: form });
			const data = await res.json().catch(() => null);
			if (!res.ok) throw new ApiError(res.status, data?.detail || `Something went wrong (${res.status}).`);
			result = data;
			step = 'result';
		} catch (e) {
			soundNote = `${(e as Error).message} The list below uses the logs only.`;
			await check(); // the logs still help
		}
	}

	async function check() {
		step = 'busy';
		error = '';
		try {
			result = await api<Result>(`/children/${childId}/cry/help`);
			step = 'result';
		} catch (e) {
			error = (e as Error).message;
			step = 'start';
		}
	}

	async function save() {
		const r = result!;
		saving = true;
		const top = listened && r.sound.is_cry ? r.sound.reasons[0] : null;
		const data: Record<string, any> = { likely_needs: r.combined.slice(0, 3).map((c) => c.need) };
		if (reason) data.reason = reason;
		if (top) Object.assign(data, { sound_reason: top.label, sound_confidence: top.probability });
		if (helped.trim()) data.soothed_by = helped.trim();
		const now = Date.now();
		const start = crying === '0' ? opened : now - Number(crying) * 60_000;
		try {
			await api(`/children/${childId}/entries`, {
				method: 'POST',
				body: { type: 'cry', started_at: toLocalInput(new Date(start).toISOString()), ended_at: toLocalInput(new Date(now).toISOString()), data }
			});
			toast('Crying saved');
			refresh();
			onclose();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			saving = false;
		}
	}

	const pct = (p: number) => `${Math.round(p * 100)}%`;
</script>

<Sheet title="Why is {name} crying?" {onclose}>
	{#if step === 'start'}
		<div class="stack">
			<button class="choice listen" onclick={listen}>
				<Icon name="mic" size={30} />
				<span><strong>Listen</strong><br /><span class="small">Hold the phone near {name} for 10 seconds. The sound guess is experimental.</span></span>
			</button>
			{#if micError}<p class="notice" role="alert">{micError}</p>{/if}
			<button class="choice" onclick={check}>
				<Icon name="check" size={30} />
				<span><strong>Just tell me what to check</strong><br /><span class="small">Uses {name}'s logs. No microphone.</span></span>
			</button>
			{#if error}<p class="error" role="alert">{error}</p>{/if}
			<button class="plain small" onclick={onmanual}>Log a crying time without help</button>
		</div>
	{:else if step === 'listening'}
		<div class="rec" role="status" aria-live="polite">
			<div class="dot" aria-hidden="true"></div>
			<p class="count" aria-label="{left} seconds left">{left}</p>
			<p><strong>Listening…</strong> Hold the phone near {name}.</p>
			<button class="wide" onclick={cancelListen}>Cancel</button>
		</div>
	{:else if step === 'busy'}
		<p class="empty" role="status">Checking…</p>
	{:else if result}
		{@const r = result}
		<div class="stack result">
			{#each r.urgent as u, i (i)}
				<article class="card urgent {u.severity}">
					<p class="sev">{u.severity === 'urgent' ? 'Urgent' : 'Look at this'}</p>
					<h3>{u.title}</h3>
					<p>{u.body}</p>
					<Cites list={u.citations} />
				</article>
			{/each}

			<section>
				<h3>Most likely, from {name}'s logs</h3>
				<ol class="needs">
					{#each r.combined as c, i (c.need)}
						{@const n = r.likely_needs.find((x) => x.need === c.need)}
						<li>
							<strong>{i + 1}. {needLabel(c.need, wording())}</strong>
							<p>{c.why}</p>
							{#if n}<Cites list={n.citations} />{/if}
						</li>
					{/each}
				</ol>
			</section>

			{#if listened || soundNote}
				<section class="sound" aria-labelledby="sound-h">
					<h3 id="sound-h">From the sound <span class="tag">Experimental</span></h3>
					{#if soundNote}
						<p class="small">{soundNote}</p>
					{:else if !r.sound.installed}
						<p class="small">{r.sound.reliability}</p>
					{:else if !r.sound.is_cry}
						<p class="small">The model did not hear crying in the recording. Try again closer to {name}, or use the list above.</p>
					{:else}
						<p class="small"><strong>A guess, not a diagnosis.</strong> {r.sound.reliability}</p>
						<ul class="bars">
							{#each r.sound.reasons as s (s.label)}
								<li>
									<span>{soundLabel(s.label)}</span>
									<span class="bar" aria-hidden="true"><span style="width: {pct(s.probability)}"></span></span>
									<span class="num">{pct(s.probability)}</span>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			{/if}

			<section>
				<h3>Things to try</h3>
				<ul class="tips">
					{#each r.suggestions.filter((s) => s.kind === 'try') as s, i (i)}
						<li>{s.text}<Cites list={s.citations} /></li>
					{/each}
				</ul>
				<h3>Get medical help</h3>
				<ul class="tips help">
					{#each r.suggestions.filter((s) => s.kind === 'help') as s, i (i)}
						<li>{s.text}<Cites list={s.citations} /></li>
					{/each}
				</ul>
			</section>

			<section class="save">
				<label class="field"><span>Crying for about</span>
					<select bind:value={crying}>
						<option value="0">It just started</option>
						{#each [5, 10, 15, 20, 30, 45, 60] as m (m)}<option value={String(m)}>{m} minutes</option>{/each}
					</select>
				</label>
				{#if r.combined.length}
					<label class="field"><span>Reason</span>
						<select value={reason} onchange={(e) => (picked = e.currentTarget.value)}>
							{#each r.combined as c, i (c.need)}<option value={c.need}>{needLabel(c.need, wording())}{i === 0 ? ' (most likely)' : ''}</option>{/each}
						</select>
					</label>
				{/if}
				<label class="field"><span>What helped (optional)</span>
					<input bind:value={helped} maxlength="200" placeholder="For example: feed, rocking" />
				</label>
				{#if error}<p class="error" role="alert">{error}</p>{/if}
				<div class="row">
					<button class="go" disabled={saving} onclick={save}><Icon name="check" /> Save to timeline</button>
					<button class="icon" aria-label="Cancel" onclick={onclose}><Icon name="close" /></button>
				</div>
			</section>
			<p class="disclaimer">General information, not medical advice.</p>
		</div>
	{/if}
</Sheet>

<style>
	.choice {
		display: flex;
		gap: 14px;
		align-items: center;
		justify-content: flex-start;
		text-align: left;
		width: 100%;
		min-height: 84px;
		padding: 14px 16px;
		border-radius: 22px;
		background: var(--cloud);
		color: var(--ink-strong);
	}
	.choice.listen {
		background: var(--coral);
	}
	.choice strong {
		font-size: 1.1rem;
	}
	.rec {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 12px 0 4px;
		text-align: center;
	}
	.dot {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: #c2334f;
		animation: pulse 1s ease-in-out infinite;
	}
	.count {
		font-size: 4.5rem;
		font-weight: 800;
		line-height: 1;
		margin: 0;
		color: var(--ink-strong);
		font-variant-numeric: tabular-nums;
	}
	@keyframes pulse {
		50% {
			opacity: 0.35;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.dot {
			animation: none;
		}
	}
	.result h3 {
		margin: 6px 0;
	}
	.urgent.urgent {
		border: 3px solid #c2334f;
		background: var(--danger-bg);
		color: var(--danger);
	}
	.urgent.attention {
		border-left: 8px solid #e2a53a;
	}
	.sev {
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
		margin: 0;
	}
	.needs,
	.tips,
	.bars {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.needs li {
		background: var(--coral);
		color: var(--ink-strong);
		border-radius: 18px;
		padding: 10px 14px;
		margin-bottom: 8px;
	}
	.needs li:not(:first-child) {
		background: var(--cloud);
	}
	.needs p {
		margin: 2px 0 0;
	}
	.sound {
		border: 2px dashed var(--line);
		border-radius: 18px;
		padding: 10px 14px;
	}
	.sound h3 {
		font-size: 1rem;
		color: var(--muted);
	}
	.tag {
		font-size: 0.75rem;
		font-weight: 800;
		text-transform: uppercase;
		background: var(--butter);
		color: var(--ink-strong);
		border-radius: 999px;
		padding: 2px 8px;
		margin-left: 6px;
	}
	.bars li {
		display: grid;
		grid-template-columns: 7.5em 1fr 3em;
		gap: 8px;
		align-items: center;
		font-size: 0.9rem;
		margin: 4px 0;
	}
	.bar {
		height: 10px;
		background: var(--cloud);
		border-radius: 999px;
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--muted);
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.tips li {
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
	}
	.tips.help li {
		font-weight: 700;
	}
	.save .row {
		display: flex;
		gap: 10px;
	}
	.save .row .go {
		flex: 1;
	}
	.save .row .icon {
		border-radius: 50%;
	}
	.go {
		background: var(--coral);
		color: var(--ink-strong);
	}
</style>
