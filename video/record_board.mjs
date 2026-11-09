// Record the board cuts with Playwright at 1920×1080.
// usage: node record_board.mjs [--base http://localhost:5173] [--only 4,5]
// Writes out/cuts/NN.webm. Each cut: open the route, wait for data, play entrance animation + interactions.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, 'out', 'cuts');
fs.mkdirSync(OUT, { recursive: true });
const args = process.argv.slice(2);
const base = args.includes('--base') ? args[args.indexOf('--base') + 1] : 'http://localhost:5173';
const only = args.includes('--only') ? args[args.indexOf('--only') + 1].split(',').map(Number) : null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Hide the elements an entrance will reveal (a style rule; the stagger's inline opacity wins over it).
async function prehide(page, sel) { await page.addStyleTag({ content: `${sel}{opacity:0}` }); }
// Navigate mid-cut without a flash of the finished page: commit → hide → settle.
async function gotoHidden(page, url, sel, readySel) {
  await page.goto(url, { waitUntil: 'commit' });
  if (sel) { try { await prehide(page, sel); } catch {} }
  if (readySel) await page.waitForSelector(readySel, { timeout: 8000 }).catch(() => {});   // the data is in: no long "loading" on camera
  else await page.waitForLoadState('networkidle');
}

// Entrance: fade children of a container in one after another.
async function stagger(page, selector, stepMs = 120, from = 'translateY(6px)') {
  await page.evaluate(({ selector, stepMs, from }) => {
    const els = [...document.querySelectorAll(selector)];
    els.forEach((el, i) => {
      el.style.transition = 'opacity .45s ease-out, transform .45s ease-out';
      el.style.opacity = '0';
      el.style.transform = from;
      setTimeout(() => { el.style.opacity = '1'; el.style.transform = 'none'; }, 150 + i * stepMs);
    });
    return els.length;
  }, { selector, stepMs, from });
}

// Count a number element from `from` to its current text over `ms`.
async function countUp(page, selector, from, ms = 1200) {
  await page.evaluate(({ selector, from, ms }) => {
    const el = document.querySelector(selector);
    if (!el) return;
    const target = parseFloat(el.textContent.replace(/[^0-9.]/g, ''));
    const suffix = el.textContent.replace(/[0-9.,]/g, '');
    const decimals = (el.textContent.match(/\.(\d+)/) || [, ''])[1].length;
    const t0 = performance.now();
    const tick = () => {
      const k = Math.min(1, (performance.now() - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      el.textContent = (from + (target - from) * e).toFixed(decimals) + suffix;
      if (k < 1) requestAnimationFrame(tick);
    };
    tick();
  }, { selector, from, ms });
}

// Per-cut scripts. Selectors use data-cut hooks the board exposes; fall back to structural selectors.
// Typographic cards (cards.html) take their numbers from out/cards.json (supers_from_data.py).
const cardNums = fs.existsSync(path.join(HERE, 'out', 'cards.json')) ? JSON.parse(fs.readFileSync(path.join(HERE, 'out', 'cards.json'), 'utf8')) : {};
const card = (name) => 'file://' + path.join(HERE, 'cards.html') + '?' + new URLSearchParams({ card: name, ...Object.fromEntries(Object.entries(cardNums).map(([k, v]) => [k, String(v)])) });

// Story v3: problem → market → product → test case → the simulation (time-lapse) → demo (collect · learn · act:
// six desks live, then the whole runs at 50×) → results → close.
const apiBase = process.env.FLEET_API || 'http://localhost:18787';
const CUTS = {
  1: { url: card('problem'), hold: 10000, async play() {} },
  2: { url: card('market'), hold: 7500, async play() {} },
  3: { route: '/surfaces', hold: 8500, prehide: '[data-surface],[data-wire]', async play(page) {
    // fast assembly: every tile is visible within 1.3 s (a slow stagger looked like a rendering error)
    await stagger(page, '[data-surface]', 220, 'translateY(8px)');
    await stagger(page, '[data-wire]', 160, 'none');
  } },
  4: { url: card('test'), hold: 6000, async play() {} },
  12: { url: 'file://' + path.join(HERE, 'sim.html'), hold: 13000, async play(page) {
    // the records: from the local cache when present (the tunnel can be slow), else from the API
    const cache = path.join(HERE, 'out', 'records.json');
    const data = fs.existsSync(cache) ? JSON.parse(fs.readFileSync(cache, 'utf8')) : await (await fetch(`${apiBase}/api/boards/northwind/records`)).json();
    const all = Array.isArray(data) ? data : (data.records || data.items || []);
    const records = all.filter((x) => (x.source || 'simulated') === 'simulated');   // the board's 309: the five Mac-take records are today's, not the chain's
    await page.evaluate((r) => window.__play(r, 6500), records);
  } },
  7: { route: '/know/knowledge', hold: 9500, prehide: '[data-lane],[data-node],[data-edge-back]', async play(page) {
    await stagger(page, '[data-lane]', 100, 'none');
    await stagger(page, '[data-node]', 45, 'scale(.92)');
    await sleep(600);
    await stagger(page, '[data-edge-back]', 160, 'none');
    await sleep(400);
    // select the bottleneck first (the inspector re-renders the map), THEN zoom in as one compositor transform anchored
    // on the Approval node — zooming before the click lost the transform on re-render and looked like a snap back
    const approval = page.locator('[data-node-id="approval"], [data-node]:has-text("Approval")').first();
    if (await approval.count()) { await approval.scrollIntoViewIfNeeded(); await approval.click(); }
    await sleep(500);
    await page.evaluate(() => {
      const inner = [...document.querySelectorAll('div')].find((d) => /scale\(/.test(d.style.transform) && /^0(px)? 0(px)?$/.test(d.style.transformOrigin));
      const vp = inner && inner.parentElement; if (!vp) return;
      const node = [...vp.querySelectorAll('[data-node]')].find((n) => /Approval/.test(n.textContent || '')) || vp;
      const vr = vp.getBoundingClientRect(), nr = node.getBoundingClientRect();
      vp.style.transformOrigin = `${nr.left + nr.width / 2 - vr.left}px ${nr.top + nr.height / 2 - vr.top}px`;
      vp.style.transition = 'transform 1.4s cubic-bezier(.2,.8,.2,1)';
      vp.style.willChange = 'transform';
      requestAnimationFrame(() => { vp.style.transform = 'scale(1.7)'; });
    });
    await sleep(2500);
  } },
  8: { route: '/know/waits', hold: 12000, prehide: '[data-kpi],[data-plan-row],[data-best-card]', async play(page) {
    // waits: 2.2 s, then the nine plans get the rest of the cut (they used to flash by)
    await stagger(page, '[data-kpi]', 90, 'translateY(6px)');
    await sleep(250);
    await page.evaluate(() => {
      const bar = document.querySelector('[data-wait-bar]');
      if (!bar) return;
      const w = bar.style.width || getComputedStyle(bar).width;
      bar.style.transition = 'none'; bar.style.width = '0px';
      requestAnimationFrame(() => { bar.style.transition = 'width .9s cubic-bezier(.2,.8,.2,1)'; bar.style.width = w; });
    });
    await sleep(2200);
    // in-app navigation (no reload, no boot): the shell stays, the rows appear as soon as the data is in
    await page.locator('nav a:has-text("Plans to test"), a:has-text("Plans to test")').first().click();
    await page.waitForSelector('[data-plan-row]', { timeout: 8000 }).catch(() => {});
    await sleep(150);
    await stagger(page, '[data-plan-row]', 110, 'translateY(8px)');
    await sleep(2200);
    await stagger(page, '[data-best-card]', 0, 'translateY(6px)');
    await sleep(500);
    const btn = page.locator('button:has-text("Approve this plan")').first();
    if (await btn.count()) await btn.hover();
  } },
  // the fleet: the FILMING RIG wall.html (six desks side by side — the board itself never shows a screen), recorded while
  // the six runs are live (record_mac_cuts.sh 9 starts them and launches this cut). The run state is fetched here in Node
  // and pushed into the page (no CORS). Long hold — build.py picks the window with START[10].
  10: { url: 'file://' + path.join(HERE, 'wall.html') + '?api=' + encodeURIComponent(apiBase),
        hold: Number(process.env.FLEET_HOLD_MS || 420000), async play(page) {
    const api = apiBase;
    const t0 = Date.now();
    while (Date.now() - t0 < this.hold) {
      try {
        const data = await (await fetch(`${api}/api/boards/northwind/fleet`)).json();
        await page.evaluate((d) => window.__setFleet(d), data);
      } catch {}
      await sleep(500);
    }
  } },
  13: { route: '/improve/results', hold: 14500, prehide: '[data-dot-before],[data-dot-after],[data-zip-row]', async play(page) {
    // results: 6.5 s on screen, then in-app to "Where to open next" and hold ~6 s (both pages used to flash by)
    await stagger(page, '[data-dot-before]', 15, 'none');
    await sleep(500);
    await stagger(page, '[data-dot-after]', 30, 'translateY(-10px)');
    await countUp(page, '[data-kpi-main]', 108.8, 1600);
    await sleep(3400);
    await page.locator('nav a:has-text("Where to open next"), a:has-text("Where to open next")').first().click();
    await page.waitForSelector('[data-zip-row]', { timeout: 15000 }).catch(() => {});
    await sleep(150);
    await stagger(page, '[data-zip-row]', 140, 'translateX(-8px)');
    await sleep(1400);
    await page.evaluate(() => document.querySelector('[data-zip-row]')?.classList.add('is-hot'));
    await countUp(page, '[data-lift-main]', 1.0, 1600);
  } },
  14: { url: card('results'), hold: 9500, async play() {} },
  15: { route: '/improve/history', hold: 5500, prehide: '[data-loop-step]', async play(page) {   // the loop only — no return to the hero
    await stagger(page, '[data-loop-step]', 320, 'none');
  } },
};

// Capture via the CDP screencast: crisp JPEG frames at device resolution whenever the page repaints,
// assembled by ffmpeg with the real frame timestamps. Viewport 1440×900 at DPR 4/3 = 1920×1080 pixels,
// which is the storyboard's own capture spec.
import { spawnSync } from 'node:child_process';
import os from 'node:os';

async function recordCut(page, cut, num) {
  const client = await page.context().newCDPSession(page);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'flowline-cut-'));
  const frames = [];
  client.on('Page.screencastFrame', async (ev) => {
    const i = frames.length;
    const f = path.join(dir, `f${String(i).padStart(6, '0')}.jpg`);
    fs.writeFileSync(f, Buffer.from(ev.data, 'base64'));
    frames.push({ f, t: ev.metadata.timestamp });
    try { await client.send('Page.screencastFrameAck', { sessionId: ev.sessionId }); } catch {}
  });
  await client.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  const t0 = Date.now();
  await cut.play(page);
  const left = cut.hold - (Date.now() - t0);
  if (left > 0) await sleep(left);
  // nudge a repaint so the last frame carries the final state, then stop
  await page.evaluate(() => { document.body.style.opacity = '0.999'; });
  await sleep(120);
  await page.evaluate(() => { document.body.style.opacity = ''; });
  await sleep(120);
  await client.send('Page.stopScreencast');
  await client.detach();
  // concat list with real durations; the last frame holds 0.5 s
  const list = path.join(dir, 'frames.txt');
  const lines = [];
  for (let i = 0; i < frames.length; i++) {
    const d = i + 1 < frames.length ? Math.max(0.001, frames[i + 1].t - frames[i].t) : 0.5;
    lines.push(`file '${frames[i].f}'`, `duration ${d.toFixed(4)}`);
  }
  lines.push(`file '${frames[frames.length - 1].f}'`);
  fs.writeFileSync(list, lines.join('\n') + '\n');
  const dest = path.join(OUT, `${String(num).padStart(2, '0')}.mp4`);
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list,
    '-vf', 'scale=1920:1080:flags=lanczos,fps=30,format=yuv420p', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', dest]);
  if (r.status !== 0) throw new Error(r.stderr.toString());
  fs.rmSync(dir, { recursive: true, force: true });
  const secs = frames.length > 1 ? frames[frames.length - 1].t - frames[0].t + 0.5 : 0;
  console.log(`cut ${String(num).padStart(2, '0')} -> ${dest}  (${frames.length} frames, ${secs.toFixed(1)} s)`);
}

const browser = await chromium.launch();
for (const [n, cut] of Object.entries(CUTS)) {
  const num = Number(n);
  if (only && !only.includes(num)) continue;
  // board routes: 1440×900 at DPR 4/3 (the storyboard's capture spec); fixed 1920-px pages (cards, sim, wall): native 1920×1080
  const ctx = await browser.newContext(cut.url
    ? { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 }
    : { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 4 / 3 });
  const page = await ctx.newPage();
  await page.goto(cut.url || base + cut.route, { waitUntil: cut.url ? 'load' : 'networkidle', timeout: 90000 });  // the wall never goes idle (frames)
  // elements that an entrance animates in are hidden BEFORE the screencast starts (the stagger reveals them); otherwise
  // the first frames show the finished page, the stagger blanks it and it "loads again"
  if (cut.prehide) await prehide(page, cut.prehide);
  await page.addStyleTag({ content: 'html{cursor:none} ::-webkit-scrollbar{display:none}' });
  await sleep(500);
  const old = path.join(OUT, `${String(num).padStart(2, '0')}.webm`);
  if (fs.existsSync(old)) fs.rmSync(old);
  await recordCut(page, cut, num);
  await ctx.close();
}
await browser.close();
