export type Theme = 'auto' | 'light' | 'dark';

export function getTheme(): Theme {
	try {
		return (localStorage.getItem('fb.theme') as Theme) || 'auto';
	} catch {
		return 'auto';
	}
}

/** Set the theme on <html>; "auto" follows the device. */
export function applyTheme(theme: Theme = getTheme()) {
	try {
		localStorage.setItem('fb.theme', theme);
	} catch {
		/* not saved; still applied for this visit */
	}
	const root = document.documentElement;
	if (theme === 'auto') delete root.dataset.theme;
	else root.dataset.theme = theme;
	const dark = theme === 'dark' || (theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
	document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#16141e' : '#fff9f3');
}
