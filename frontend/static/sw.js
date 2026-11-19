// Frecklebubby service worker: app-shell cache and Web Push. Never caches /api or /mcp.
const CACHE = 'fb-shell-v1';
const SHELL = ['/', '/manifest.webmanifest', '/icon.svg', '/icon-192.png'];

self.addEventListener('install', (event) => {
	event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches.keys()
			.then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
			.then(() => self.clients.claim())
	);
});

self.addEventListener('fetch', (event) => {
	const req = event.request;
	const url = new URL(req.url);
	if (req.method !== 'GET' || url.origin !== location.origin) return;
	if (url.pathname.startsWith('/api') || url.pathname.startsWith('/mcp')) return;

	if (req.mode === 'navigate') {
		// Network first so a new version shows at once; the cached shell works offline.
		event.respondWith(
			fetch(req)
				.then((res) => {
					const copy = res.clone();
					caches.open(CACHE).then((c) => c.put('/', copy));
					return res;
				})
				.catch(() => caches.match('/'))
		);
		return;
	}
	// Hashed build files never change: cache first. Other files: network, then cache.
	const immutable = url.pathname.startsWith('/_app/immutable/');
	event.respondWith(
		(immutable ? caches.match(req) : Promise.resolve(undefined)).then(
			(hit) =>
				hit ||
				fetch(req)
					.then((res) => {
						if (res.ok) {
							const copy = res.clone();
							caches.open(CACHE).then((c) => c.put(req, copy));
						}
						return res;
					})
					.catch(() => caches.match(req))
		)
	);
});

self.addEventListener('push', (event) => {
	let data = {};
	try {
		data = event.data ? event.data.json() : {};
	} catch {
		data = { title: 'Frecklebubby', body: event.data ? event.data.text() : '' };
	}
	event.waitUntil(
		self.registration.showNotification(data.title || 'Frecklebubby', {
			body: data.body || '',
			icon: '/icon-192.png',
			badge: '/icon-192.png',
			tag: data.id ? `fb-${data.id}` : data.kind || 'fb',
			data: { url: data.kind === 'test' ? '/settings/notifications' : '/notifications' }
		})
	);
});

self.addEventListener('notificationclick', (event) => {
	event.notification.close();
	const target = (event.notification.data && event.notification.data.url) || '/';
	event.waitUntil(
		self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
			for (const w of wins) {
				if ('focus' in w) {
					w.navigate(target);
					return w.focus();
				}
			}
			return self.clients.openWindow(target);
		})
	);
});
