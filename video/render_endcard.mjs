// Render endcard.html to out/cuts/16.png. usage: node render_endcard.mjs [github.com/org/repo]
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const url = process.argv[2] || '';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(path.join(HERE, 'endcard.html')).href + (url ? `?url=${encodeURIComponent(url)}` : ''));
await page.waitForTimeout(300);
await page.screenshot({ path: path.join(HERE, 'out', 'cuts', '16.png') });
await browser.close();
console.log('out/cuts/16.png');
