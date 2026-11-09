// Small inline icons used across the board. Square caps, as in the storyboard.
export const Logo = ({ size = 17, stroke = '#fff', width = 2.4 }: { size?: number; stroke?: string; width?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth={width} strokeLinecap="square" aria-hidden="true">
    <path d="M3 17h6V7h6v6h6" />
  </svg>
);
export const ArrowRight = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" aria-hidden="true">
    <path d="M4 12h15" /><path d="M13 6l6 6-6 6" />
  </svg>
);
export const ShareIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true">
    <path d="M12 15V3" /><path d="M7 8l5-5 5 5" /><path d="M5 13v8h14v-8" />
  </svg>
);
export const ExportIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true">
    <path d="M12 3v12" /><path d="M7 10l5 5 5-5" /><path d="M5 21h14" />
  </svg>
);
export const Check = ({ size = 11, stroke = '#fff', width = 3 }: { size?: number; stroke?: string; width?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth={width} strokeLinecap="square" aria-hidden="true">
    <path d="M5 12l5 5 9-10" />
  </svg>
);
export const AgentMark = ({ size = 11, stroke = '#5a48c0' }: { size?: number; stroke?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2.4" strokeLinecap="square" aria-hidden="true">
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="M9 9h6v6H9z" />
  </svg>
);
/** Agent badge: violet tinted square with the skill mark. */
export const AgentBadge = () => (
  <span title="Prepared by the agent" aria-label="Prepared by the agent" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: 2, background: '#f3f1fd', border: '1px solid rgba(109,91,208,0.3)', flex: '0 0 18px' }}>
    <AgentMark />
  </span>
);
export const InboxIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#30373f" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true">
    <path d="M3 13l2.5-8h13L21 13v6H3z" /><path d="M3 13h5l1.5 2.5h5L16 13h5" />
  </svg>
);
export const NotchIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#30373f" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true">
    <path d="M3 5h18v12H3z" /><path d="M9 5v2.5h6V5" /><path d="M1.5 20h21" />
  </svg>
);
export const DigestIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#30373f" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true">
    <path d="M4 4h16v16H4z" /><path d="M8 9h8M8 13h8M8 17h5" />
  </svg>
);
export const ShieldCheck = ({ size = 20, stroke = '#fff' }: { size?: number; stroke?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" />
  </svg>
);
/** Node kind glyphs for the ontology (12px box). */
export const KindGlyph = ({ kind, stroke = '#4d5353', size = 12 }: { kind: 'event' | 'step' | 'decision' | 'skill'; stroke?: string; size?: number }) => {
  const s = kind === 'skill' ? '#6D5BD0' : stroke;
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke={s} strokeWidth="1.5" aria-hidden="true">
      {kind === 'event' && <circle cx="6" cy="6" r="4" />}
      {kind === 'step' && <rect x="2" y="2" width="8" height="8" />}
      {kind === 'decision' && <path d="M6 1.5 L10.5 6 L6 10.5 L1.5 6 Z" />}
      {kind === 'skill' && (<><path d="M6 1v3M6 8v3M1 6h3M8 6h3" /><rect x="4.5" y="4.5" width="3" height="3" /></>)}
    </svg>
  );
};
