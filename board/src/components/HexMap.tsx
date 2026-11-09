// Hex-binned map of ZIP rows (lat/lon → pointy-top hex grid), coloured by predicted net new businesses.
// Geography decorations (river, highways) are drawn only for Austin, TX; they are fixed facts, not model output.
import type { ZipRow } from '../lib/types';

export const BUCKETS = ['#eef1f4', '#d6e2fb', '#a9c2f8', '#6f97f3', '#3B73FF'];
export const bucket = (p: number) => BUCKETS[Math.min(BUCKETS.length - 1, Math.max(0, Math.floor(p + 0.0001)))];

interface Cell { q: number; r: number; zip: ZipRow }

export function layoutHexes(zips: ZipRow[], W: number, H: number, cols: number) {
  const lats = zips.map((z) => z.lat), lons = zips.map((z) => z.lon);
  // focus on the core: trim the 10% farthest-flung ZIPs from the bounding box
  const sortedLat = [...lats].sort((a, b) => a - b), sortedLon = [...lons].sort((a, b) => a - b);
  const q = (arr: number[], p: number) => arr[Math.min(arr.length - 1, Math.max(0, Math.floor(p * (arr.length - 1))))];
  const lat0 = q(sortedLat, 0.14), lat1 = q(sortedLat, 0.86), lon0 = q(sortedLon, 0.14), lon1 = q(sortedLon, 0.86);
  const cosLat = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180);
  const hexW = W / cols; // flat width of a pointy hex
  const R = hexW / Math.sqrt(3);
  const rowH = R * 1.5;
  const rows = Math.floor((H - R) / rowH);
  const spanLon = (lon1 - lon0) * cosLat || 1, spanLat = lat1 - lat0 || 1;
  // keep aspect: scale so that the data fits in the grid either way
  const sx = (cols - 1) / spanLon, sy = (rows - 1) / spanLat;
  const s = Math.min(sx, sy);
  const offX = ((cols - 1) - spanLon * s) / 2, offY = ((rows - 1) - spanLat * s) / 2;
  const toGrid = (z: ZipRow) => ({
    gx: (z.lon - lon0) * cosLat * s + offX,
    gy: (lat1 - z.lat) * s + offY,
  });
  const center = (qq: number, rr: number) => ({ x: hexW * (qq + 0.5 + (rr % 2 ? 0.5 : 0)), y: R + rr * rowH });
  const taken = new Map<string, Cell>();
  const key = (qq: number, rr: number) => `${qq},${rr}`;
  const inBounds = (qq: number, rr: number) => qq >= 0 && qq < cols - (rr % 2 ? 1 : 0) && rr >= 0 && rr <= rows;
  const cells: Cell[] = [];
  const ranked = [...zips].sort((a, b) => a.rank - b.rank);
  for (const z of ranked) {
    const { gx, gy } = toGrid(z);
    // nearest cell by pixel distance, searching outward
    const px = (gx + 0.5) * hexW, py = R + gy * rowH;
    let best: { qq: number; rr: number; d: number } | null = null;
    const rr0 = Math.round((py - R) / rowH);
    for (let dr = -4; dr <= 4; dr++) {
      const rr = rr0 + dr;
      const qq0 = Math.round(px / hexW - 0.5 - (rr % 2 ? 0.5 : 0));
      for (let dq = -4; dq <= 4; dq++) {
        const qq = qq0 + dq;
        if (!inBounds(qq, rr) || taken.has(key(qq, rr))) continue;
        const c = center(qq, rr);
        const dd = (c.x - px) ** 2 + (c.y - py) ** 2;
        if (!best || dd < best.d) best = { qq, rr, d: dd };
      }
    }
    if (!best) continue;
    const cell = { q: best.qq, r: best.rr, zip: z };
    taken.set(key(best.qq, best.rr), cell);
    cells.push(cell);
  }
  // filler ring: empty cells adjacent to an occupied one, for a contiguous blob
  const fillers: { q: number; r: number }[] = [];
  const nb = (qq: number, rr: number) => (rr % 2 ? [[1, 0], [-1, 0], [0, 1], [1, 1], [0, -1], [1, -1]] : [[1, 0], [-1, 0], [0, 1], [-1, 1], [0, -1], [-1, -1]]).map(([a, b]) => [qq + a, rr + b]);
  const seen = new Set<string>();
  for (const c of cells) for (const [qq, rr] of nb(c.q, c.r)) {
    const k = key(qq, rr);
    if (!inBounds(qq, rr) || taken.has(k) || seen.has(k)) continue;
    seen.add(k); fillers.push({ q: qq, r: rr });
  }
  const hexPts = (cx: number, cy: number, rad: number) => Array.from({ length: 6 }, (_, i) => { const a = (Math.PI / 180) * (60 * i - 30); return `${(cx + rad * Math.cos(a)).toFixed(1)},${(cy + rad * Math.sin(a)).toFixed(1)}`; }).join(' ');
  const project = (lat: number, lon: number) => { const gx = (lon - lon0) * cosLat * s + offX, gy = (lat1 - lat) * s + offY; return { x: (gx + 0.5) * hexW, y: R + gy * rowH }; };
  return { cells, fillers, center, R, hexPts, project, rows, hexW };
}

const AUSTIN = {
  river: [[30.40, -97.91], [30.37, -97.86], [30.33, -97.80], [30.27, -97.77], [30.25, -97.73], [30.24, -97.70], [30.20, -97.64], [30.17, -97.58]],
  i35: [[30.75, -97.68], [30.55, -97.68], [30.40, -97.69], [30.30, -97.72], [30.25, -97.74], [30.15, -97.78], [30.00, -97.86]],
  mopac: [[30.50, -97.78], [30.40, -97.75], [30.33, -97.76], [30.28, -97.77], [30.22, -97.80], [30.17, -97.82]],
  labels: [['I-35', 30.73, -97.68], ['MoPac', 30.49, -97.80], ['Colorado R.', 30.19, -97.60], ['L. Travis', 30.42, -97.95]],
};

export function HexMap({ zips, width = 188, height = 232, cols = 12, city, showRanks = true, pickLabel = true, decorate = true, legendInside = false }:
  { zips: ZipRow[]; width?: number; height?: number; cols?: number; city?: string; showRanks?: boolean; pickLabel?: boolean; decorate?: boolean; legendInside?: boolean }) {
  const L = layoutHexes(zips, width, height, cols);
  const pick = L.cells.find((c) => c.zip.pick);
  const austin = decorate && city?.startsWith('Austin');
  const path = (pts: number[][]) => pts.map(([la, lo], i) => { const p = L.project(la, lo); return `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`; }).join(' ');
  const font = 'Geist Mono, ui-monospace, monospace';
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`ZIP codes shaded by predicted new businesses; ${pick ? `${pick.zip.zip} ${pick.zip.name} ranks first` : ''}`} style={{ display: 'block' }}>
      <rect width={width} height={height} rx="4" fill="#f7f8f9" />
      {L.fillers.map((f) => { const c = L.center(f.q, f.r); return <polygon key={`f${f.q},${f.r}`} points={L.hexPts(c.x, c.y, L.R)} fill="#f1f3f5" stroke="#fff" strokeWidth="1.1" />; })}
      {L.cells.map((c) => { const p = L.center(c.q, c.r); return <polygon key={c.zip.zip} points={L.hexPts(p.x, p.y, L.R)} fill={bucket(c.zip.predicted)} stroke="#fff" strokeWidth="1.1"><title>{c.zip.zip} {c.zip.name} · {c.zip.predicted >= 0 ? '+' : ''}{c.zip.predicted}</title></polygon>; })}
      {austin && (
        <g fill="none" strokeLinecap="round">
          <path d={path(AUSTIN.river)} stroke="#fff" strokeWidth="6.5" /><path d={path(AUSTIN.river)} stroke="#bcd0e6" strokeWidth="4" />
          <path d={path(AUSTIN.i35)} stroke="#fff" strokeWidth="3.2" /><path d={path(AUSTIN.i35)} stroke="#7d868c" strokeWidth="1" />
          <path d={path(AUSTIN.mopac)} stroke="#fff" strokeWidth="3.2" /><path d={path(AUSTIN.mopac)} stroke="#7d868c" strokeWidth="1" />
        </g>
      )}
      {showRanks && L.cells.filter((c) => !c.zip.pick && c.zip.rank <= 5).map((c) => { const p = L.center(c.q, c.r); return (
        <g key={`r${c.zip.zip}`}><circle cx={p.x} cy={p.y} r="5.2" fill="#fff" stroke="#171717" strokeWidth="1" /><text x={p.x} y={p.y + 2.4} fontFamily={font} fontSize="7" fontWeight="600" fill="#000" textAnchor="middle">{c.zip.rank}</text></g>
      ); })}
      {pick && (() => { const p = L.center(pick.q, pick.r); const right = p.x < width * 0.7; return (
        <g>
          <polygon points={L.hexPts(p.x, p.y, L.R)} fill={bucket(pick.zip.predicted)} stroke="#171717" strokeWidth="2" />
          {pickLabel && <>
            <rect x={right ? p.x + L.R + 1 : p.x - L.R - 41} y={p.y - 1} width="40" height="14" rx="2" fill="#171717" />
            <text x={right ? p.x + L.R + 21 : p.x - L.R - 21} y={p.y + 8.8} fontFamily={font} fontSize="8" fill="#fff" textAnchor="middle">{pick.zip.zip}</text>
          </>}
        </g>
      ); })()}
      {austin && AUSTIN.labels.map(([t, la, lo]) => { const p = L.project(la as number, lo as number); return <text key={t as string} x={Math.min(width - 4, Math.max(4, p.x))} y={Math.min(height - 4, Math.max(10, p.y))} fontFamily={font} fontSize="7" fill="#30373f" stroke="#fff" strokeWidth="2.4" paintOrder="stroke" strokeLinejoin="round" textAnchor="middle">{t}</text>; })}
      <g transform={`translate(${width - 12} ${height - 14})`}><path d="M0 -8 L4 2 L0 0 L-4 2 Z" fill="#30373f" /><text x="0" y="10" fontFamily={font} fontSize="7" fill="#30373f" textAnchor="middle">N</text></g>
      {legendInside && (
        <g transform={`translate(8 ${height - 14})`}>
          <rect x="-4" y="-5" width="118" height="14" rx="2" fill="rgba(255,255,255,0.85)" />
          <text x="0" y="5" fontFamily={font} fontSize="7" fill="#4d5353">GROWTH</text>
          {BUCKETS.map((c, i) => <rect key={c} x={34 + i * 16} y="-2" width="15" height="8" fill={c} />)}
        </g>
      )}
    </svg>
  );
}
