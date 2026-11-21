// One assistant chat turn over Server-Sent Events (Assistant page and voice commands).
import { AI_DOWN, apiRaw } from './api';
import { refresh } from './app.svelte';
import type { Proposal } from './Proposals.svelte';
import type { Citation } from './SourceSheet.svelte';

// M14: what a chat turn saved ("Logged" block) and what it did not save without a check (proposals).
export type Item = { action: 'entry' | 'timer'; type: string; summary: string; entry_id?: number | null; timer_action?: string | null; undone: boolean; unsure?: string | null };
export type Logged = { items: Item[]; proposals: Proposal[]; message: string };
export type Msg = { id?: number; role: 'user' | 'assistant'; content: string; citations: Citation[]; logged?: Logged | null; waiting?: boolean };

/** Send the text and fill `answer` (a $state object) while the events arrive. Throws an Error with a plain message. */
export async function streamChat(cid: number, text: string, answer: Msg, voice = false) {
	try {
		const res = await apiRaw(`/children/${cid}/assistant/chat`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
			body: JSON.stringify({ message: text, voice })
		});
		if (!res.ok || !res.body) {
			const d = await res.json().catch(() => null);
			throw new Error((res.status === 503 || res.status === 429) && d?.detail ? d.detail : AI_DOWN);
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
				if (ev !== 'waiting') answer.waiting = false;
				if (ev === 'waiting') answer.waiting = true;
				else if (ev === 'logged') {
					answer.logged = { items: data.items, proposals: data.proposals, message: data.message };
					answer.id = data.message_id;
					refresh();
				} else if (ev === 'token') answer.content += data.text;
				else if (ev === 'citations') answer.citations = data.citations;
				else if (ev === 'done') answer.id = data.message_id;
				else if (ev === 'error') throw new Error(data.detail || AI_DOWN);
			}
		}
	} catch (err) {
		throw err instanceof TypeError ? new Error(AI_DOWN) : err;
	}
}
