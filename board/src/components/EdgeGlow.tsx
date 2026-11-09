// "Flowline is using this screen": a wavy gradient glow hugging the inside edge of a live desk frame.
// WebGL canvas drawing one full-screen triangle with design/edge-glow.frag (verbatim). One rAF loop is shared
// by every mounted glow; it only runs while at least one glow is active (or fading out), and each canvas renders
// at DPR 1 (the glow is soft). The desks themselves draw nothing — this border is the board's.
import { useEffect, useRef } from 'react';

const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }
`;

// design/edge-glow.frag — do not edit here; the Mac app's Metal port must match it.
const FRAG = `
precision highp float;

uniform float iTime;
uniform vec2  iResolution;
uniform float hue;
uniform float thickness;

varying vec2 vUv;

vec3 rgb2yiq(vec3 c) {
  return vec3(dot(c, vec3(0.299, 0.587, 0.114)), dot(c, vec3(0.596, -0.274, -0.322)), dot(c, vec3(0.211, -0.523, 0.312)));
}
vec3 yiq2rgb(vec3 c) {
  return vec3(c.x + 0.956 * c.y + 0.621 * c.z, c.x - 0.272 * c.y - 0.647 * c.z, c.x - 1.106 * c.y + 1.703 * c.z);
}
vec3 adjustHue(vec3 color, float hueDeg) {
  float h = radians(hueDeg);
  vec3 yiq = rgb2yiq(color);
  float ca = cos(h), sa = sin(h);
  yiq.yz = vec2(yiq.y * ca - yiq.z * sa, yiq.y * sa + yiq.z * ca);
  return yiq2rgb(yiq);
}

vec3 hash33(vec3 p3) {
  p3 = fract(p3 * vec3(0.1031, 0.11369, 0.13787));
  p3 += dot(p3, p3.yxz + 19.19);
  return -1.0 + 2.0 * fract(vec3(p3.x + p3.y, p3.x + p3.z, p3.y + p3.z) * p3.zyx);
}
float snoise3(vec3 p) {
  const float K1 = 0.333333333;
  const float K2 = 0.166666667;
  vec3 i = floor(p + (p.x + p.y + p.z) * K1);
  vec3 d0 = p - (i - (i.x + i.y + i.z) * K2);
  vec3 e = step(vec3(0.0), d0 - d0.yzx);
  vec3 i1 = e * (1.0 - e.zxy);
  vec3 i2 = 1.0 - e.zxy * (1.0 - e);
  vec3 d1 = d0 - (i1 - K2);
  vec3 d2 = d0 - (i2 - K1);
  vec3 d3 = d0 - 0.5;
  vec4 h = max(0.6 - vec4(dot(d0, d0), dot(d1, d1), dot(d2, d2), dot(d3, d3)), 0.0);
  vec4 n = h * h * h * h * vec4(dot(d0, hash33(i)), dot(d1, hash33(i + i1)), dot(d2, hash33(i + i2)), dot(d3, hash33(i + 1.0)));
  return dot(vec4(31.316), n);
}

float light1(float intensity, float attenuation, float dist) { return intensity / (1.0 + dist * attenuation); }
float light2(float intensity, float attenuation, float dist) { return intensity / (1.0 + dist * dist * attenuation); }

const vec3 baseColor0 = vec3(0.239, 0.353, 1.0);   // blue
const vec3 baseColor1 = vec3(0.616, 0.0, 1.0);     // purple
const vec3 baseColor2 = vec3(1.0, 0.373, 0.122);   // orange

void main() {
  vec2 p = vUv * iResolution;                 // pixel position
  vec2 h = iResolution * 0.5;
  vec2 q = abs(p - h) - h;
  float sd = -max(q.x, q.y);                  // distance inward from the nearest edge, px (≥ 0 inside)

  // slow waves along the edge + finer ripple; breathing pulse
  vec2 k = p / iResolution.y;
  float n0 = snoise3(vec3(k * 1.6, iTime * 0.35)) * 0.5 + 0.5;
  float n1 = snoise3(vec3(k * 4.0 + 7.0, iTime * 0.6)) * 0.5 + 0.5;
  float pulse = sin(iTime * 1.5) * 0.06;
  float th = thickness * (0.65 + 0.6 * n0 + 0.2 * n1 + pulse);   // wavy glow depth, px

  float d = sd / th;                                              // 0 at the edge → 1 at the inner boundary
  float glow = light1(1.0, 6.0, d) * smoothstep(1.4, 0.0, d);

  // a bright point orbiting the perimeter (one lap ≈ 7.9 s)
  float ang = atan(p.y - h.y, p.x - h.x);
  float cl = cos(ang - iTime * 0.8) * 0.5 + 0.5;
  float hi = light2(1.2, 3.0, (1.0 - cl) * 3.0) * smoothstep(1.0, 0.0, d);

  vec3 col = mix(adjustHue(baseColor1, hue), adjustHue(baseColor2, hue), cl);
  col = mix(col, adjustHue(baseColor0, hue), n0);
  col = col * glow + vec3(0.6) * hi * glow;
  col = clamp(col, 0.0, 1.0);
  float alpha = max(max(col.r, col.g), col.b);
  gl_FragColor = vec4(col, alpha);            // premultiplied
}
`;

interface Renderer { draw(t: number): void }

// ---- one animation loop for every glow on the page ------------------------------------------------------
const live = new Set<Renderer>();
let raf = 0;
const t0 = performance.now();
function tick() {
  raf = 0;
  if (live.size === 0) return;
  const t = (performance.now() - t0) / 1000;
  live.forEach((r) => r.draw(t));
  raf = requestAnimationFrame(tick);
}
function register(r: Renderer) { live.add(r); if (!raf) raf = requestAnimationFrame(tick); }
function unregister(r: Renderer) { live.delete(r); if (live.size === 0 && raf) { cancelAnimationFrame(raf); raf = 0; } }

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader | null {
  const sh = gl.createShader(type);
  if (!sh) return null;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    console.warn('edge-glow shader:', gl.getShaderInfoLog(sh));
    gl.deleteShader(sh);
    return null;
  }
  return sh;
}

class GlowRenderer implements Renderer {
  gl: WebGLRenderingContext | null = null;
  uTime: WebGLUniformLocation | null = null;
  uRes: WebGLUniformLocation | null = null;
  w = 0; h = 0;
  constructor(public canvas: HTMLCanvasElement, public hue: number, public thickness: number) {
    const gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: false, powerPreference: 'low-power' });
    if (!gl) return;
    const vs = compile(gl, gl.VERTEX_SHADER, VERT), fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    const prog = gl.createProgram();
    if (!vs || !fs || !prog) return;
    gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.warn('edge-glow link:', gl.getProgramInfoLog(prog)); return; }
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW); // full-screen triangle
    const aPos = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
    gl.uniform1f(gl.getUniformLocation(prog, 'hue'), hue);
    gl.uniform1f(gl.getUniformLocation(prog, 'thickness'), thickness);
    this.uTime = gl.getUniformLocation(prog, 'iTime');
    this.uRes = gl.getUniformLocation(prog, 'iResolution');
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); // premultiplied
    gl.clearColor(0, 0, 0, 0);
    this.gl = gl;
  }
  resize(w: number, h: number) {
    w = Math.max(1, Math.round(w)); h = Math.max(1, Math.round(h));   // DPR 1 on purpose
    if (w === this.w && h === this.h) return;
    this.w = w; this.h = h;
    this.canvas.width = w; this.canvas.height = h;
    this.gl?.viewport(0, 0, w, h);
  }
  draw(t: number) {
    const gl = this.gl;
    if (!gl || this.w === 0) return;
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(this.uTime, t);
    gl.uniform2f(this.uRes, this.w, this.h);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  // No WEBGL_lose_context here: React StrictMode re-mounts the effect on the same <canvas>, and a lost context is
  // what getContext() hands back afterwards (shaders then fail to compile with an empty log). GC frees it.
  dispose() { this.gl = null; }
}

/**
 * Glow overlay for a frame box. Put it inside a `position: relative` wrapper that is exactly the frame's box;
 * it fills it (inset 0) and ignores pointer events. `active` fades it in over 300 ms and out over 400 ms;
 * rendering stops once the fade-out is done so idle cards cost nothing.
 */
export function EdgeGlow({ active, thickness = 26, hue = 0 }: { active: boolean; thickness?: number; hue?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const rend = useRef<GlowRenderer | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const r = new GlowRenderer(canvas, hue, thickness);
    rend.current = r;
    const ro = new ResizeObserver((entries) => { const b = entries[0]?.contentRect; if (b) r.resize(b.width, b.height); });
    ro.observe(canvas);
    r.resize(canvas.clientWidth, canvas.clientHeight);
    return () => { ro.disconnect(); unregister(r); r.dispose(); rend.current = null; };
  }, [hue, thickness]);

  useEffect(() => {
    const r = rend.current;
    if (!r) return;
    if (active) { register(r); return; }
    const id = window.setTimeout(() => unregister(r), 450); // keep drawing through the fade-out
    return () => window.clearTimeout(id);
  }, [active]);

  return (
    <canvas
      ref={ref}
      className="edge-glow"
      aria-hidden="true"
      data-glow={active ? 'on' : 'off'}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 3, borderRadius: 'inherit',
        opacity: active ? 1 : 0, transition: `opacity ${active ? 300 : 400}ms ease`, willChange: 'opacity' }}
    />
  );
}
