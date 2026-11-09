#!/usr/bin/env node
// Flowline executor agent loop on the Vercel AI SDK.
//
//   node run.mjs --run-id ID --target desk1 --skill fill_deck_from_sheet|proposal_packet|reconcile_quotes|signature_packet --inputs '{}' [--bridge http://127.0.0.1:8790] [--max-steps 25]
//
// The Python service owns the desktop; this process talks to it over the local bridge:
//   POST /desk/{target}/action   computer actions (screenshot → base64 PNG scaled to ≤1280 wide)
//   POST /desk/{target}/run      shell command on the target machine (bash tool)
//   GET  /desk/{target}/sheet    .ods → items/total
//   GET  /desk/{target}/deck_cells  table of the live (unsaved) deck
//   POST /runs/{id}/events       step events (tool calls, text, screenshots, timings)
// Exit code: 0 finished, 2 step limit reached, 1 error. SIGTERM (Stop) aborts the loop.
import { ToolLoopAgent, stepCountIs, tool } from 'ai';
import { createAnthropic } from '@ai-sdk/anthropic';
import { z } from 'zod';
import { skillPrompt } from './skills.mjs';

const args = parseArgs(process.argv.slice(2));
const runId = args['run-id'] || `local-${Date.now()}`;
const target = args.target || 'desk1';
const skillId = args.skill || 'fill_deck_from_sheet';
const inputs = JSON.parse(args.inputs || '{}');
const bridge = (args.bridge || process.env.FLOWLINE_EXECUTOR_URL || 'http://127.0.0.1:8790').replace(/\/$/, '');
const maxSteps = Number(args['max-steps'] || process.env.FLOWLINE_MAX_STEPS || 25);
const modelId = process.env.FLOWLINE_MODEL || 'claude-sonnet-5-5';

if (!process.env.ANTHROPIC_API_KEY) {
  console.error('agent: needs ANTHROPIC_API_KEY');
  process.exit(1);
}

const controller = new AbortController();
let stopped = false;
for (const sig of ['SIGTERM', 'SIGINT']) {
  process.on(sig, () => { stopped = true; controller.abort(); });
}

// ---------------------------------------------------------------- bridge
async function post(path, body) {
  const r = await fetch(bridge + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
  return r.json();
}
async function get(path) {
  const r = await fetch(bridge + path);
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
  return r.json();
}
async function event(ev) {
  try { await post(`/runs/${runId}/events`, { at: new Date().toISOString(), ...ev }); }
  catch (e) { console.error('agent: event post failed:', e.message); }
}
const summarize = (o) => JSON.stringify(o).slice(0, 200);
// The SDK starts every tool call of a step at once; desktop actions must run one after another, in call order.
let chain = Promise.resolve();
const serial = (fn) => { const p = chain.then(fn, fn); chain = p.catch(() => {}); return p; };
const guard = () => { if (stopped) return 'Run stopped by the user. Do nothing more.'; return null; };

// ---------------------------------------------------------------- tools
const anthropic = createAnthropic(); // ANTHROPIC_API_KEY from the environment, never logged
const view = await get(`/desk/${target}/view`);

const computer = anthropic.tools.computerToolset_20260801({
  execute: (input) => serial(async () => {
    const s = guard(); if (s) return s;
    const t0 = performance.now();
    let r;
    try { r = await post(`/desk/${target}/action`, { ...input, run_id: runId }); }
    catch (e) { r = { ok: false, error: e.message }; }
    const seconds = (performance.now() - t0) / 1000;
    await event({ type: 'tool_call', name: 'computer', action: input.action, input: summarize(input), seconds, ok: !!r.ok,
                  screenshot: r.path || null, error: r.error || null });
    if (!r.ok) return `Error: ${r.error}`;
    if (r.image) return { type: 'image', data: r.image, mediaType: 'image/png' };
    return r.result ?? 'OK';
  }),
  toModelOutput: ({ output }) =>
    typeof output === 'string'
      ? { type: 'text', value: output }
      : { type: 'content', value: [{ type: 'file', data: { type: 'data', data: output.data }, mediaType: output.mediaType || 'image/png' }] },
});

async function runShell(command) { return serial(() => runShellNow(command)); }
async function runShellNow(command) {
  const s = guard(); if (s) return s;
  const t0 = performance.now();
  let r;
  try { r = await post(`/desk/${target}/run`, { cmd: command, timeout: 120 }); }
  catch (e) { r = { exit: -1, output: `Error: ${e.message}` }; }
  await event({ type: 'tool_call', name: 'bash', input: summarize({ command }), seconds: (performance.now() - t0) / 1000, ok: r.exit === 0 });
  return `exit=${r.exit}\n${(r.output || '').slice(0, 20000)}`;
}
const bash = anthropic.tools.bash_20250124({ execute: async ({ command }) => runShell(command || 'true') });

const readSheet = tool({
  description: 'Read a pricing spreadsheet (.ods) on the target machine: Item/Amount rows and the Total row, as JSON. Use this instead of the GUI.',
  inputSchema: z.object({ path: z.string().describe('path of the .ods file on the target') }),
  execute: ({ path }) => serial(async () => {
    const s = guard(); if (s) return s;
    const t0 = performance.now();
    try {
      const r = await get(`/desk/${target}/sheet?path=${encodeURIComponent(path)}`);
      await event({ type: 'tool_call', name: 'read_sheet', input: summarize({ path }), seconds: (performance.now() - t0) / 1000, ok: true, output: summarize(r) });
      return r;
    } catch (e) {
      await event({ type: 'tool_call', name: 'read_sheet', input: summarize({ path }), seconds: (performance.now() - t0) / 1000, ok: false, error: e.message });
      return `Error: ${e.message}`;
    }
  }),
});

const readDeckCells = tool({
  description: 'Read the table on a slide of the deck that is open in Impress, from the live document (nothing is saved). Returns rows of cell text, top to bottom, and whether the document is modified.',
  inputSchema: z.object({ deck: z.string().describe('deck file name or path'), slide: z.number().int().describe('1-based slide number') }),
  execute: ({ deck, slide }) => serial(async () => {
    const s = guard(); if (s) return s;
    const t0 = performance.now();
    try {
      const r = await get(`/desk/${target}/deck_cells?deck=${encodeURIComponent(deck)}&slide=${slide}`);
      await event({ type: 'tool_call', name: 'read_deck_cells', input: summarize({ deck, slide }), seconds: (performance.now() - t0) / 1000, ok: true, output: summarize(r) });
      return r;
    } catch (e) {
      await event({ type: 'tool_call', name: 'read_deck_cells', input: summarize({ deck, slide }), seconds: (performance.now() - t0) / 1000, ok: false, error: e.message });
      return `Error: ${e.message}`;
    }
  }),
});

// ---------------------------------------------------------------- loop
const { instructions, prompt, steps: stepLabels, tools: toolNames } = skillPrompt(skillId, inputs, view);

const reportStep = tool({
  description: `Tell the person which of the ${stepLabels.length} steps you are on. step: ${stepLabels.map((l, i) => `${i + 1} ${l}`).join(', ')}. status "now" when you start a step, "done" when it is finished. progress [done, total] while filling cells.`,
  inputSchema: z.object({
    step: z.number().int().min(1).max(stepLabels.length),
    status: z.enum(['now', 'done']),
    detail: z.string().describe('one short line for the person, e.g. "Three line items and the total: $4,290"'),
    progress: z.array(z.number().int()).optional().describe('[done, total] while filling'),
  }),
  execute: ({ step, status, detail, progress }) => serial(async () => {
    await event({ type: 'step', step, status, detail, progress: progress && progress.length === 2 ? progress : null });
    const s = guard(); if (s) return s;
    return 'OK';
  }),
});

// The skill decides what the model may use: the packet skills get the screen (computer) and report_step only.
const allTools = { computer, bash, read_sheet: readSheet, read_deck_cells: readDeckCells, report_step: reportStep };
// On a person's own machine (target "mac") the agent never gets a shell: GUI actions and the read-only tools only.
const allowed = target === 'mac' ? toolNames.filter((n) => n !== 'bash') : toolNames;
const tools = Object.fromEntries(allowed.map((n) => {
  if (!allTools[n]) throw new Error(`skill ${skillId} asks for unknown tool ${n}`);
  return [n, allTools[n]];
}));

async function runAgent() {
  const agent = new ToolLoopAgent({
    model: anthropic(modelId),
    instructions,
    tools,
    stopWhen: stepCountIs(maxSteps),
  });
  return agent.generate({
    prompt,
    abortSignal: controller.signal,
    onStepFinish: async (step) => {
      const text = (step.text || '').trim();
      const usage = step.usage || {};
      await event({ type: 'model', finish: step.finishReason, text: text.slice(0, 500), tool_calls: (step.toolCalls || []).map((c) => c.toolName),
                    input_tokens: usage.inputTokens, output_tokens: usage.outputTokens });
    },
  });
}

const t0 = performance.now();
let result;
try {
  result = await runAgent();
} catch (e) {
  if (stopped) {
    await event({ type: 'done', status: 'stopped', seconds: (performance.now() - t0) / 1000 });
    process.exit(130);
  }
  const msg = String(e && e.stack || e).slice(0, 2000);
  console.error('agent: error:', msg);
  await event({ type: 'error', error: msg, seconds: (performance.now() - t0) / 1000 });
  process.exit(1);
}

const exhausted = result.finishReason === 'tool-calls';
await event({ type: 'done', status: exhausted ? 'max_steps' : 'finished', text: (result.text || '').slice(0, 1000),
              steps: result.steps.length, finish: result.finishReason, model: modelId, seconds: (performance.now() - t0) / 1000,
              input_tokens: result.totalUsage?.inputTokens, output_tokens: result.totalUsage?.outputTokens });
console.log(JSON.stringify({ status: exhausted ? 'max_steps' : 'finished', steps: result.steps.length, text: result.text }));
process.exit(exhausted ? 2 : 0);

// ---------------------------------------------------------------- util
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const v = argv[i + 1] !== undefined && !argv[i + 1].startsWith('--') ? argv[++i] : 'true';
      out[k] = v;
    }
  }
  return out;
}
