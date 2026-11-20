<script lang="ts">
	// Simple rounded line icons, 24 x 24.
	const P: Record<string, string> = {
		home: 'M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z',
		history: 'M12 7v5l3 2M3.5 12a8.5 8.5 0 1 0 2.5-6M3 4v4h4',
		reports: 'M5 20V11M12 20V5M19 20v-6M3 20h18',
		assistant: 'M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-4 3v-3H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM8 11h.01M12 11h.01M16 11h.01',
		settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18.7 10.2L21.1 10.7L21.1 13.3L18.7 13.8L18.0 15.4L19.3 17.5L17.5 19.3L15.5 18.0L13.8 18.7L13.3 21.1L10.7 21.1L10.2 18.7L8.6 18.0L6.5 19.3L4.7 17.5L6.0 15.4L5.3 13.8L2.9 13.3L2.9 10.7L5.3 10.2L6.0 8.5L4.7 6.5L6.5 4.7L8.5 6.0L10.2 5.3L10.7 2.9L13.3 2.9L13.8 5.3L15.5 6.0L17.5 4.7L19.3 6.5L18.0 8.5z',
		bell: 'M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0',
		plus: 'M12 5v14M5 12h14',
		close: 'M6 6l12 12M18 6 6 18',
		left: 'M15 5l-7 7 7 7',
		right: 'M9 5l7 7-7 7',
		down: 'M5 9l7 7 7-7',
		trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13',
		play: 'M8 5v14l11-7z',
		pause: 'M8 5v14M16 5v14',
		stop: 'M7 7h10v10H7z',
		swap: 'M7 7h12l-3-3M17 17H5l3 3',
		send: 'M4 12 20 4l-6 16-3-7z',
		download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
		upload: 'M12 20V9M7 14l5-5 5 5M5 4h14',
		check: 'M5 12l5 5 9-10',
		sparkle: 'M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z',
		sleep: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z',
		nursing: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z',
		bottle: 'M10 2h4M10 4h4v2l2 3v11a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V9l2-3zM8 12h3M8 16h3',
		nappy: 'M3 7h18v3a9 9 0 0 1-9 9 9 9 0 0 1-9-9zM3 10c3 0 5 2 5.5 5M21 10c-3 0-5 2-5.5 5',
		solids: 'M3 11h18a9 9 0 0 1-18 0zM15 4l-3 7M9 20h6',
		pump: 'M8 3h8v4a4 4 0 0 1-8 0zM12 11v3M8 14h8l-1 7H9z',
		potty: 'M5 9h14v2a7 7 0 0 1-14 0zM8 17l-1 4h10l-1-4M9 5h6',
		growth: 'M4 20 20 4M7 17l2 2M10 14l2 2M13 11l2 2M16 8l2 2',
		temperature: 'M10 13.5V5a2 2 0 1 1 4 0v8.5a4 4 0 1 1-4 0zM12 9v7',
		medicine: 'M10.5 20.5a5 5 0 0 1-7-7l6-6a5 5 0 0 1 7 7zM7 10l7 7',
		activity: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3.5 9h17M3.5 15h17M12 3c-3 3-3 15 0 18M12 3c3 3 3 15 0 18',
		milestone: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z',
		note: 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5',
		confined: 'M8 3h3l2 9h5a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2zM9 12h4M5 21h14',
		cry: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8.5 10h2M13.5 10h2M9.5 16.5c1.4-1.2 3.6-1.2 5 0M8 12.5c-.9 1.3-.9 2.3 0 2.8',
		mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
		sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5',
		link: 'M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1'
	};
	let { name, size = 24 }: { name: string; size?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
	stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
	<path d={P[name] ?? P.note} />
</svg>
