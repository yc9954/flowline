// Lane-graph layout for the ontology: lanes = roles, x = order in time (longest path over forward edges),
// edges routed as straight lines or rounded elbows. Pure functions; the page renders the result.
import type { OntEdge, OntNode, Ontology } from './types';

export const NODE_W = 90, NODE_H = 66, LANE_H = 90, LANE_TOP = 40, ROLE_COL = 96, X0 = 114, BOTTOM_PAD = 34;
const GAP_SAME = 114, GAP_CHANGE = 72, GAP_WAIT = 56, RADIUS = 6;

export interface Placed { node: OntNode; col: number; lane: number; x: number; y: number }
export interface RoutedEdge {
  edge: OntEdge; d: string; from: Placed; to?: Placed;
  label?: { x: number; y: number; align: 'center' | 'left' | 'right' };
  longWait: boolean; hot: boolean; back: boolean; parallel: boolean;
}
export interface Layout {
  width: number; height: number; lanes: { role: string; steps: number; external?: boolean; y: number }[];
  placed: Map<string, Placed>; edges: RoutedEdge[]; naturalWidth: number;
}

export function layoutGraph(ont: Ontology, selectedId: string | null, targetWidth?: number): Layout {
  const laneRoles = ont.roles.map((r) => r.role as string);
  for (const n of ont.nodes) if (!laneRoles.includes(n.role)) laneRoles.push(n.role);
  const laneOf = (role: string) => laneRoles.indexOf(role);
  const byId = new Map(ont.nodes.map((n) => [n.id, n]));
  const fwd = ont.edges.filter((e) => e.kind !== 'back' && byId.has(e.from) && byId.has(e.to));

  // longest path (DAG over forward edges; cycles are cut by visiting state)
  const col = new Map<string, number>();
  const state = new Map<string, 0 | 1 | 2>();
  const preds = new Map<string, string[]>();
  for (const e of fwd) preds.set(e.to, [...(preds.get(e.to) ?? []), e.from]);
  const depth = (id: string): number => {
    if (col.has(id)) return col.get(id)!;
    if (state.get(id) === 1) return 0;
    state.set(id, 1);
    const p = preds.get(id) ?? [];
    const c = p.length ? Math.max(...p.map((q) => depth(q) + 1)) : 0;
    state.set(id, 2); col.set(id, c);
    return c;
  };
  ont.nodes.forEach((n) => depth(n.id));
  const maxCol = Math.max(0, ...col.values());

  // gaps between columns
  const gaps: number[] = [];
  for (let c = 1; c <= maxCol; c++) {
    const into = fwd.filter((e) => col.get(e.to) === c && col.get(e.from) === c - 1);
    const same = into.some((e) => byId.get(e.from)!.role === byId.get(e.to)!.role);
    let g = same ? GAP_SAME : GAP_CHANGE;
    if (into.some((e) => (e.wait_h ?? 0) > 0 && byId.get(e.to)!.bottleneck)) g += GAP_WAIT;
    gaps.push(g);
  }
  const natural = X0 + gaps.reduce((a, b) => a + b, 0) + NODE_W + 12;
  let scale = 1;
  if (targetWidth && targetWidth > natural && gaps.length) scale = (targetWidth - X0 - NODE_W - 12) / gaps.reduce((a, b) => a + b, 0);
  const xs: number[] = [X0];
  for (const g of gaps) xs.push(xs[xs.length - 1] + g * scale);
  const width = Math.max(natural, targetWidth ?? 0);
  const height = LANE_TOP + laneRoles.length * LANE_H + BOTTOM_PAD;

  const placed = new Map<string, Placed>();
  for (const n of ont.nodes) {
    const lane = laneOf(n.role);
    placed.set(n.id, { node: n, col: col.get(n.id) ?? 0, lane, x: xs[col.get(n.id) ?? 0], y: LANE_TOP + lane * LANE_H + 12 });
  }
  const lanes = laneRoles.map((role, i) => {
    const r = ont.roles.find((x) => x.role === role);
    return { role, steps: r?.steps ?? ont.nodes.filter((n) => n.role === role).length, external: r?.external, y: LANE_TOP + i * LANE_H };
  });

  // --- edge routing ---
  const cx = (p: Placed) => p.x + NODE_W / 2, cy = (p: Placed) => p.y + NODE_H / 2;
  const inFwd = new Map<string, number>();
  for (const e of fwd) inFwd.set(e.to, (inFwd.get(e.to) ?? 0) + 1);
  const backOut = new Set(ont.edges.filter((e) => e.kind === 'back').map((e) => e.from));
  const topChannelUsed: number[] = [];
  const r = RADIUS;
  const edges: RoutedEdge[] = [];

  for (const e of ont.edges) {
    const A = placed.get(e.from);
    if (!A) continue;
    const B = placed.get(e.to);
    const hot = selectedId != null && (e.from === selectedId || e.to === selectedId);
    const base = { edge: e, from: A, to: B, hot, back: e.kind === 'back', parallel: e.kind === 'parallel', longWait: false };

    if (!B) {
      // stub: a short drop with an end tick, label below
      const px = cx(A), y0 = A.y + NODE_H;
      edges.push({ ...base, d: `M${px} ${y0} L${px} ${y0 + 14} M${px - 5} ${y0 + 14} h10`, label: { x: px, y: y0 + 26, align: 'center' } });
      continue;
    }
    const longWait = e.kind !== 'back' && (e.wait_h ?? 0) > 0 && !!B.node.bottleneck;

    if (e.kind !== 'back') {
      if (A.lane === B.lane) {
        const x1 = A.x + NODE_W, x2 = B.x, y = cy(A);
        edges.push({ ...base, longWait, d: `M${x1} ${y} L${x2} ${y}`, label: e.label ? { x: (x1 + x2) / 2, y: y - 12, align: 'center' } : undefined });
        continue;
      }
      const down = B.lane > A.lane;
      const yB = cy(B);
      if ((inFwd.get(e.to) ?? 0) >= 2) {
        // converge: leave A on the right, elbow in the gap, enter B from the left
        const x1 = A.x + NODE_W, mx = (x1 + B.x) / 2, yA = cy(A), s = down ? 1 : -1;
        const d = `M${x1} ${yA} L${mx - r} ${yA} Q${mx} ${yA} ${mx} ${yA + s * r} L${mx} ${yB - s * r} Q${mx} ${yB} ${mx + r} ${yB} L${B.x} ${yB}`;
        edges.push({ ...base, longWait, d, label: e.label ? { x: mx, y: (yA + yB) / 2, align: 'left' } : undefined });
      } else {
        // fan: leave A from the bottom/top, elbow at B's lane, enter B from the left
        const px = A.x + (backOut.has(A.node.id) ? 58 : NODE_W / 2);
        const y0 = down ? A.y + NODE_H : A.y, s = down ? 1 : -1;
        const d = `M${px} ${y0} L${px} ${yB - s * r} Q${px} ${yB} ${px + r} ${yB} L${B.x} ${yB}`;
        const label = e.label
          ? (Math.abs(yB - y0) > 60 && !longWait
            ? { x: px, y: (y0 + yB) / 2, align: 'center' as const }
            : { x: (px + B.x) / 2, y: yB, align: 'center' as const })
          : undefined;
        edges.push({ ...base, longWait, d, label });
      }
      continue;
    }

    // back edges (target is earlier)
    const overlapL = Math.max(A.x, B.x), overlapR = Math.min(A.x + NODE_W, B.x + NODE_W);
    if (overlapR - overlapL >= 20 && A.lane !== B.lane) {
      const x = (overlapL + overlapR) / 2;
      const up = B.lane < A.lane;
      const y1 = up ? A.y : A.y + NODE_H, y2 = up ? B.y + NODE_H : B.y;
      edges.push({ ...base, d: `M${x} ${y1} L${x} ${y2}`, label: { x: x + 8, y: (y1 + y2) / 2, align: 'left' } });
      continue;
    }
    if (B.lane < A.lane) {
      const px = A.x + 16;
      let yc = cy(B) + 8;
      const blocked = [...placed.values()].some((p) => p !== B && p !== A && p.lane === B.lane && p.x + NODE_W > B.x + NODE_W && p.x < px);
      if (!blocked) {
        const d = `M${px} ${A.y} L${px} ${yc + r} Q${px} ${yc} ${px - r} ${yc} L${B.x + NODE_W} ${yc}`;
        edges.push({ ...base, d, label: { x: (px + B.x + NODE_W) / 2, y: yc, align: 'center' } });
      } else {
        yc = LANE_TOP + (B.lane + 1) * LANE_H; // boundary below B's lane
        const bx = cx(B) + 20;
        const d = `M${px} ${A.y} L${px} ${yc + r} Q${px} ${yc} ${px - r} ${yc} L${bx + r} ${yc} Q${bx} ${yc} ${bx} ${yc - r} L${bx} ${B.y + NODE_H}`;
        edges.push({ ...base, d, label: { x: (px + bx) / 2, y: yc, align: 'center' } });
      }
      continue;
    }
    // target below (or same lane): go over the top channel
    const k = topChannelUsed.length; topChannelUsed.push(k);
    const yc = 18 - k * 12;
    const px = A.x + 16, bx = cx(B);
    const d = `M${px} ${A.y} L${px} ${yc + r} Q${px} ${yc} ${px - r} ${yc} L${bx + r} ${yc} Q${bx} ${yc} ${bx} ${yc + r} L${bx} ${B.y}`;
    edges.push({ ...base, d, label: { x: (px + bx) / 2, y: yc, align: 'center' } });
  }

  return { width, height, lanes, placed, edges, naturalWidth: natural };
}
