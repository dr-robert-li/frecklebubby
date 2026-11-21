// Voice commands: push to talk, and hands free with the keyword "Hey Bubby" or "OK Bubby".
// The page records, the server changes the speech into text (Whisper), the assistant chat logs or answers.
import { api, ApiError } from './api';
import { app } from './app.svelte';
import { streamChat, type Msg } from './chat';

export type Speak = 'off' | 'handsfree' | 'all';
type Prefs = { speak: Speak; float: boolean; side: 'left' | 'right'; y: number };
const KEY = 'fb.voice';
const DEFAULT: Prefs = { speak: 'off', float: false, side: 'right', y: 60 };

function load(): Prefs {
	try {
		return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
	} catch {
		return { ...DEFAULT };
	}
}

export const voice = $state({
	recording: false, // push to talk records now
	handsFree: false,
	armed: false, // the keyword came alone: the next phrase is the command
	busy: false, // a command runs
	error: '',
	heard: '', // the words of the last command
	turn: null as Msg | null, // the answer to the last command, when no page shows it
	prefs: load()
});

export function savePrefs() {
	try {
		localStorage.setItem(KEY, JSON.stringify(voice.prefs));
	} catch {
		/* not saved; still used for this visit */
	}
}

export const canVoice = () => !!app.config?.voice && typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;

/** A page that shows the chat (Assistant) takes the commands here; if not, the voice card shows the answer. */
let handler: ((text: string) => Promise<Msg | null>) | null = null;
export function onCommand(h: typeof handler) {
	handler = h;
	return () => void (handler === h && (handler = null));
}

// --- microphone ----------------------------------------------------------------------------------------------------

const RATE = 16000;
const MAX_SECONDS = 28;
let stream: MediaStream | null = null;
let ctx: AudioContext | null = null;
let node: ScriptProcessorNode | null = null;
let wantRec = false;
let chunks: Float32Array[] = [];

async function open() {
	if (ctx) return;
	stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
	ctx = new AudioContext();
	// ponytail: ScriptProcessorNode is deprecated but works in all browsers with no worklet file; move to AudioWorklet if a browser removes it.
	node = ctx.createScriptProcessor(4096, 1, 1);
	node.onaudioprocess = (e) => onAudio(new Float32Array(e.inputBuffer.getChannelData(0)));
	ctx.createMediaStreamSource(stream).connect(node);
	node.connect(ctx.destination); // the node gives silence; some browsers run it only when connected
}

function close() {
	if (voice.handsFree || voice.recording || wantRec) return;
	stream?.getTracks().forEach((t) => t.stop());
	node?.disconnect();
	ctx?.close().catch(() => {});
	stream = ctx = node = null;
}

const seconds = (parts: Float32Array[]) => parts.reduce((n, p) => n + p.length, 0) / (ctx?.sampleRate ?? 48000);

/** Float samples at the device rate -> WAV file: one channel, 16 bit, 16 kHz. */
function wav(parts: Float32Array[], rate: number): Blob {
	const all = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
	let at = 0;
	for (const p of parts) (all.set(p, at), (at += p.length));
	const step = rate / RATE;
	const n = Math.floor(all.length / step);
	const view = new DataView(new ArrayBuffer(44 + n * 2));
	const str = (o: number, s: string) => [...s].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
	str(0, 'RIFF');
	view.setUint32(4, 36 + n * 2, true);
	str(8, 'WAVEfmt ');
	view.setUint32(16, 16, true);
	view.setUint16(20, 1, true);
	view.setUint16(22, 1, true);
	view.setUint32(24, RATE, true);
	view.setUint32(28, RATE * 2, true);
	view.setUint16(32, 2, true);
	view.setUint16(34, 16, true);
	str(36, 'data');
	view.setUint32(40, n * 2, true);
	for (let i = 0; i < n; i++) {
		// the mean of the input samples for one output sample (a simple low-pass filter)
		const a = Math.floor(i * step);
		const b = Math.max(a + 1, Math.floor((i + 1) * step));
		let sum = 0;
		for (let j = a; j < b; j++) sum += all[j];
		view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, sum / (b - a))) * 32767, true);
	}
	return new Blob([view], { type: 'audio/wav' });
}

async function toText(parts: Float32Array[], rate: number, wake: boolean) {
	const form = new FormData();
	form.append('file', wav(parts, rate), 'voice.wav');
	form.append('wake', String(wake));
	return api<{ heard: boolean; text: string }>('/voice/transcribe', { method: 'POST', form });
}

const micError = (e: unknown) =>
	e instanceof ApiError ? e.message : (e as Error)?.name === 'NotAllowedError' ? 'The microphone is blocked. Allow it in the browser settings.' : 'The microphone does not work on this device.';

// --- hands free: find phrases (speech between silence) -------------------------------------------------------------

let floor = 0.005; // the background noise level
let pre: Float32Array[] = [];
let phrase: Float32Array[] | null = null;
let quiet = 0;
let loud = 0;
let queue = Promise.resolve();
let armTimer: ReturnType<typeof setTimeout>;

function onAudio(d: Float32Array) {
	if (voice.recording) {
		chunks.push(d);
		if (seconds(chunks) > MAX_SECONDS) pttStop();
		return;
	}
	// Do not hear the app's own voice, and do not stack commands.
	if (!voice.handsFree || voice.busy || speechSynthesis?.speaking) {
		phrase = null;
		return;
	}
	const rate = ctx!.sampleRate;
	const dur = d.length / rate;
	let sum = 0;
	for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
	const rms = Math.sqrt(sum / d.length);
	const speech = rms > Math.max(0.012, floor * 3);
	if (!phrase) {
		if (!speech) {
			floor = floor * 0.95 + rms * 0.05;
			pre = [...pre.slice(-2), d];
			return;
		}
		phrase = [...pre, d];
		pre = [];
		quiet = 0;
		loud = dur;
		return;
	}
	phrase.push(d);
	if (speech) (quiet = 0), (loud += dur);
	else quiet += dur;
	if (quiet < 0.8 && seconds(phrase) < 15) return;
	const done = phrase;
	phrase = null;
	// ponytail: a sound that goes on for 15 s raises the noise level so the app does not send it again and again
	if (quiet < 0.8) floor = Math.max(floor, rms / 2);
	if (loud >= 0.3) queue = queue.then(() => onPhrase(done, rate)).catch(() => {});
}

async function onPhrase(parts: Float32Array[], rate: number) {
	if (!voice.handsFree) return;
	const armed = voice.armed;
	let r;
	try {
		r = await toText(parts, rate, !armed);
	} catch (e) {
		// Too many requests or no network: say it once, then listen again.
		voice.error = e instanceof ApiError ? e.message : '';
		return;
	}
	if (armed) {
		disarm();
		// "Hey Bubby" again with the command is also good.
		const text = r.text.replace(/^\W*(hey|hi|ok|okay)\W+bubb\w*\W*/i, '');
		if (text) await run(text, true);
		return;
	}
	if (!r.heard) return;
	beep();
	if (r.text) await run(r.text, true);
	else {
		voice.armed = true;
		clearTimeout(armTimer);
		armTimer = setTimeout(disarm, 8000);
	}
}

function disarm() {
	clearTimeout(armTimer);
	voice.armed = false;
}

/** A short sound: the app heard the keyword. */
function beep() {
	if (!ctx) return;
	const osc = ctx.createOscillator();
	const gain = ctx.createGain();
	osc.frequency.value = 880;
	gain.gain.setValueAtTime(0.15, ctx.currentTime);
	gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);
	osc.connect(gain).connect(ctx.destination);
	osc.start();
	osc.stop(ctx.currentTime + 0.2);
}

let lock: WakeLockSentinel | null = null;
async function keepAwake() {
	// The browser stops the microphone when the screen is off: keep the screen on while hands free is on.
	try {
		if (voice.handsFree && document.visibilityState === 'visible') lock = await navigator.wakeLock?.request('screen');
	} catch {
		/* no wake lock (low battery, old browser): hands free works until the screen goes off */
	}
}
if (typeof document !== 'undefined') document.addEventListener('visibilitychange', keepAwake);

export async function setHandsFree(on: boolean) {
	voice.error = '';
	if (!on) {
		voice.handsFree = false;
		disarm();
		lock?.release().catch(() => {});
		lock = null;
		close();
		return;
	}
	try {
		await open();
		voice.handsFree = true;
		keepAwake();
	} catch (e) {
		voice.error = micError(e);
	}
}

// --- push to talk --------------------------------------------------------------------------------------------------

export async function pttStart() {
	if (voice.recording || wantRec || voice.busy) return;
	voice.error = '';
	wantRec = true;
	speechSynthesis?.cancel();
	try {
		await open();
	} catch (e) {
		wantRec = false;
		voice.error = micError(e);
		return;
	}
	if (!wantRec) return close(); // released before the microphone was ready
	chunks = [];
	voice.recording = true;
}

export async function pttStop() {
	wantRec = false;
	if (!voice.recording) return;
	voice.recording = false;
	const parts = chunks;
	const rate = ctx!.sampleRate;
	chunks = [];
	const long = seconds(parts) >= 0.4;
	close();
	if (!long) return;
	voice.busy = true;
	try {
		const r = await toText(parts, rate, false);
		if (r.text) await run(r.text, false);
		else voice.error = 'I did not hear words. Try again.';
	} catch (e) {
		voice.error = micError(e);
	} finally {
		voice.busy = false;
	}
}

export const pttToggle = () => (voice.recording ? pttStop() : pttStart());

// --- run a command -------------------------------------------------------------------------------------------------

async function run(text: string, handsFree: boolean) {
	voice.busy = true;
	voice.error = '';
	voice.heard = text;
	voice.turn = null;
	try {
		let msg: Msg | null;
		if (handler) msg = await handler(text);
		else {
			if (!app.childId) throw new Error('Add a child first.');
			voice.turn = { role: 'assistant', content: '', citations: [] };
			msg = voice.turn;
			await streamChat(app.childId, text, msg, true);
		}
		if (msg && (voice.prefs.speak === 'all' || (voice.prefs.speak === 'handsfree' && handsFree))) say(spoken(msg));
	} catch (e) {
		voice.error = (e as Error).message;
		if (voice.turn && !voice.turn.content && !voice.turn.logged) voice.turn = null;
	} finally {
		voice.busy = false;
	}
}

/** The answer as words to read aloud: what was logged, what is not sure, then the answer with no source numbers. */
export function spoken(m: Msg): string {
	const out: string[] = [];
	for (const it of m.logged?.items ?? []) out.push(`Logged: ${it.summary}.` + (it.unsure ? ` Not sure: ${it.unsure}.` : ''));
	if (m.logged?.proposals.length) out.push(m.logged.message || 'Check the items on the screen.');
	if (!m.logged?.items.length && !m.content && m.logged?.message) out.push(m.logged.message);
	out.push(m.content.replace(/\[\d+\]/g, '').replace(/^- /gm, ''));
	return out.join(' ').replace(/–/g, ',').trim();
}

export function say(text: string) {
	if (!text || typeof speechSynthesis === 'undefined') return;
	speechSynthesis.cancel();
	speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}
