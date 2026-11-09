// Playwright screenshots + smoke checks for the board (routes, legacy redirect, empty state, no demo literals).
// usage: node scripts/smoke.mjs [http://localhost:5173]   — needs the dev server (with the contract stub) and ../video's playwright.
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire(new URL('../../video/package.json', import.meta.url));
const { chromium } = require('playwright');

const base = process.argv[2] ?? 'http://localhost:5173';
const OUT = new URL('../shots/', import.meta.url).pathname;
fs.mkdirSync(OUT, { recursive: true });

// a board with no data, created through the (stubbed) contract
const mk = await fetch(`${base}/api/boards`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'Harbor Dental', industry: '621210', mail_domain: 'harbordental.com', timezone: 'America/Los_Angeles' }) });
const created = await mk.json();
console.log('created board', mk.status, created.id);
const addP = await fetch(`${base}/api/boards/${created.id}/people`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'Maya Lin', role: 'Finance', email: 'maya@harbordental.com', target: 'mac', skill_id: 'reconcile_quotes', pre_approved: true }) });
const person = await addP.json();
console.log('added person', addP.status, person.id);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(`[console] ${m.text().slice(0, 200)}`); });
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`));

async function shot(name, route, { wait = 'networkidle', settle = 600, expectText, expectUrl } = {}) {
  await page.goto(base + route, { waitUntil: wait, timeout: 30000 });
  await page.waitForTimeout(settle);
  const url = page.url().replace(base, '');
  const text = await page.evaluate(() => document.body.innerText);
  const ok = (!expectText || text.includes(expectText)) && (!expectUrl || url.startsWith(expectUrl));
  const file = `${OUT}/${name}.png`;
  await page.screenshot({ path: file, fullPage: false });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}  ${route} -> ${url}  ${expectText ? `has "${expectText}": ${text.includes(expectText)}` : ''}  title="${await page.title()}"`);
  if (!ok) console.log('   text head:', text.slice(0, 400).replace(/\n/g, ' | '));
  return text;
}

await shot('boards', '/', { expectText: 'Northwind Fitness' });
await shot('b-northwind-know-waits', '/b/northwind/know/waits', { expectText: 'Where work waits' });
const empty = await shot('b-empty-know-waits', `/b/${created.id}/know/waits`, { expectText: 'No approved records yet' });
console.log('   empty-state line:', (empty.match(/No approved records yet[\s\S]{0,220}/) || [''])[0].replace(/\n/g, ' '));
await shot('b-nosuch-know-waits', '/b/nosuch-board/know/waits', { expectText: 'no board called' });
await shot('legacy-know-waits', '/know/waits?x=1', { expectUrl: '/b/northwind/know/waits?x=1', expectText: 'Where work waits' });
await shot('legacy-surfaces', '/surfaces', { expectUrl: '/b/northwind/surfaces' });
await shot('b-northwind-surfaces', '/b/northwind/surfaces', { expectText: 'One knowledge' });
await shot('b-northwind-people', '/b/northwind/people', { expectText: 'People & invites' });
await shot('b-empty-people', `/b/${created.id}/people`, { expectText: 'Maya Lin' });
await shot('b-northwind-run-fleet', '/b/northwind/run/fleet', { expectText: 'Agents on desks' });
await shot('b-empty-run-fleet', `/b/${created.id}/run/fleet`);
await shot('b-northwind-decide-expand', '/b/northwind/decide/expand?industry=722515', { expectText: 'Where to open next' });
await shot('b-northwind-fixtures', '/b/northwind/know/waits?fixtures=1', { expectText: 'fixture' });
await shot('b-northwind-records', '/b/northwind/know/records', { expectText: 'Approved records' });
await shot('b-northwind-history', '/b/northwind/improve/history', { expectText: 'Process history' });
await shot('b-northwind-model', '/b/northwind/trust/model', { expectText: 'Model check' });
await shot('b-northwind-knowledge', '/b/northwind/know/knowledge', { expectText: 'Company knowledge' });
await shot('b-northwind-opening', '/b/northwind/decide/opening', { expectText: 'Opening branch' });
await shot('b-northwind-plans', '/b/northwind/improve/plans', { expectText: 'Plans to test' });
await shot('b-northwind-results', '/b/northwind/improve/results', { expectText: 'Results' });

// issue an invite through the UI on the empty board
await page.goto(`${base}/b/${created.id}/people`, { waitUntil: 'networkidle' });
await page.click('button:has-text("Issue invite")');
await page.waitForSelector('[data-invite]', { timeout: 5000 });
const inviteText = await page.evaluate(() => document.querySelector('[data-invite]')?.textContent ?? '');
console.log('invite card:', inviteText.slice(0, 220));
await page.screenshot({ path: `${OUT}/b-empty-people-invite.png` });

// literal scan: every board page of the empty board must not mention the demo company
const pages = ['know/waits', 'know/knowledge', 'know/records', 'improve/plans', 'improve/results', 'improve/history', 'trust/model', 'decide/expand', 'decide/opening', 'run/fleet', 'people'];
for (const p of pages) {
  await page.goto(`${base}/b/${created.id}/${p}`, { waitUntil: 'networkidle' });
  const t = await page.evaluate(() => document.body.innerText);
  const bad = ['Northwind', 'gym', 'club', 'Austin', 'Dana', '78704'].filter((w) => t.includes(w));
  console.log(`literal check ${p}: ${bad.length ? 'FOUND ' + bad.join(',') : 'clean'}`);
}
console.log(errors.length ? `console errors:\n${errors.join('\n')}` : 'no console errors');
await browser.close();
