// Render the SVG app icons to PNG with Chromium. Run once after changing frontend/static/icon*.svg.
import { chromium } from '@playwright/test';
import { readFileSync } from 'node:fs';

const dir = new URL('../frontend/static/', import.meta.url);
const browser = await chromium.launch();
for (const [svg, name] of [['icon.svg', 'icon'], ['icon-maskable.svg', 'icon-maskable']]) {
	const src = readFileSync(new URL(svg, dir), 'utf8');
	for (const size of [192, 512]) {
		const page = await browser.newPage({ viewport: { width: size, height: size } });
		await page.setContent(`<style>*{margin:0}svg{width:${size}px;height:${size}px;display:block}</style>${src}`);
		await page.screenshot({ path: new URL(`${name}-${size}.png`, dir).pathname, omitBackground: true });
		await page.close();
	}
}
await browser.close();
