// Flowline "agent is using this screen" edge glow — reference fragment shader (GLSL ES 1.0).
// A wavy, noise-driven gradient glow hugging the edges of a rectangle (a screen, or a live desk frame),
// with a bright point orbiting the perimeter and a slow breathing pulse. Ported from the GradientOrb shader
// (blue / purple / orange, YIQ hue rotation, hash simplex noise). Both renderers must match this look:
//   board/  → WebGL canvas over each fleet card and the large desk view (uniform thickness ≈ 26 px)
//   agent-mac/ → Metal port (SwiftUI .colorEffect / CAMetalLayer) on a click-through full-screen window (thickness ≈ 90 px)
// Uniforms: iTime (s), iResolution (px), hue (deg, 0 = as drawn), thickness (px, base glow depth).
// Output is premultiplied RGBA; everything beyond ~1.4 × thickness from the edge is fully transparent.

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
