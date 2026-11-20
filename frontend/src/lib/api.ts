// REST client and sign-in. Dev mode: X-Dev-User header. Clerk mode: session token.
import type { Clerk } from '@clerk/clerk-js';

export type Config = {
	auth_mode: 'dev' | 'clerk';
	clerk_publishable_key: string;
	vapid_public_key: string;
	version: string;
};

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

const DEV_USER_KEY = 'fb.devUser';
let config: Config | null = null;
let clerk: Clerk | null = null;

export function devUser(): string {
	try {
		return localStorage.getItem(DEV_USER_KEY) || 'dev@example.com';
	} catch {
		return 'dev@example.com';
	}
}

export function setDevUser(email: string) {
	try {
		localStorage.setItem(DEV_USER_KEY, email);
	} catch {
		/* private mode: header falls back to the default user */
	}
}

/** Load /config and, in Clerk mode, Clerk itself. Returns false when the user must sign in. */
export async function initAuth(): Promise<{ config: Config; signedIn: boolean }> {
	config = await api<Config>('/config', { anonymous: true });
	if (config.auth_mode !== 'clerk') return { config, signedIn: true };
	// clerk-js 6 has no sign-in form of its own: the form comes from @clerk/ui.
	const [{ Clerk }, { ui }] = await Promise.all([import('@clerk/clerk-js'), import('@clerk/ui')]);
	clerk = new Clerk(config.clerk_publishable_key);
	await clerk.load({ ui });
	return { config, signedIn: !!clerk.user };
}

export function mountSignIn(node: HTMLDivElement) {
	clerk?.mountSignIn(node);
}

export async function signOut() {
	await clerk?.signOut();
	location.href = '/';
}

async function authHeaders(): Promise<Record<string, string>> {
	if (config?.auth_mode === 'clerk') {
		const token = await clerk?.session?.getToken();
		return token ? { Authorization: `Bearer ${token}` } : {};
	}
	return { 'X-Dev-User': devUser() };
}

type Opts = { method?: string; body?: unknown; anonymous?: boolean; form?: FormData };

/** Fetch with auth. Returns parsed JSON, or null for 204. Throws ApiError with the server's plain message. */
export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
	const headers: Record<string, string> = opts.anonymous ? {} : await authHeaders();
	let body: BodyInit | undefined = opts.form;
	if (opts.body !== undefined) {
		headers['Content-Type'] = 'application/json';
		body = JSON.stringify(opts.body);
	}
	let res: Response;
	try {
		res = await fetch('/api/v1' + path, { method: opts.method ?? 'GET', headers, body });
	} catch {
		throw new ApiError(0, 'No connection. Check your network and try again.');
	}
	if (res.status === 204) return null as T;
	const data = await res.json().catch(() => null);
	if (!res.ok) throw new ApiError(res.status, data?.detail || `Something went wrong (${res.status}).`);
	return data as T;
}

/** Raw authed fetch, for blobs and event streams. */
export async function apiRaw(path: string, init: RequestInit = {}): Promise<Response> {
	const headers = { ...(await authHeaders()), ...(init.headers as Record<string, string>) };
	return fetch('/api/v1' + path, { ...init, headers });
}

export const AI_DOWN = 'The assistant is not available now.';

/** Message for features that may not exist yet on this server or whose model is down. */
export function softMessage(e: unknown, fallback = AI_DOWN): string {
	if (e instanceof ApiError && (e.status === 404 || e.status === 503 || e.status === 0 || e.status >= 500))
		return e.status === 503 || e.status === 501 ? e.message : fallback;
	return e instanceof Error ? e.message : fallback;
}
