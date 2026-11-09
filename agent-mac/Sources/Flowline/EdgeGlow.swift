import AppKit
import Metal
import QuartzCore

/// Metal port of design/edge-glow.frag: a wavy, noise-driven gradient glow hugging the screen edges, a bright point
/// orbiting the perimeter and a slow breathing pulse. Rendered on a CAMetalLayer at 1 px per point (the compositor
/// upscales; the glow is soft) by a CADisplayLink at the display's refresh rate. Output is premultiplied RGBA and the
/// fragment shader returns exactly 0 everywhere farther than ~2.2 × thickness from an edge, so the desktop is untouched.
final class EdgeGlowView: NSView {
    static let pixelsPerPoint: CGFloat = 1
    var hue: Float = 0
    var thickness: Float = 90

    private let device: MTLDevice?
    private let queue: MTLCommandQueue?
    private var pipeline: MTLRenderPipelineState?
    private var link: CADisplayLink?
    private let start = CACurrentMediaTime()
    private var metalLayer: CAMetalLayer? { layer as? CAMetalLayer }

    struct Uniforms {
        var time: Float
        var resolution: SIMD2<Float>   // points
        var hue: Float
        var thickness: Float           // points
        var drawable: SIMD2<Float>     // pixels
    }

    override init(frame: NSRect) {
        device = MTLCreateSystemDefaultDevice()
        queue = device?.makeCommandQueue()
        super.init(frame: frame)
        wantsLayer = true
        layerContentsRedrawPolicy = .never
        buildPipeline()
    }
    required init?(coder: NSCoder) { fatalError("not used") }

    override func makeBackingLayer() -> CALayer {
        let l = CAMetalLayer()
        l.device = device
        l.pixelFormat = .bgra8Unorm
        l.isOpaque = false
        l.framebufferOnly = true
        l.contentsScale = EdgeGlowView.pixelsPerPoint
        l.backgroundColor = nil
        return l
    }
    override var wantsUpdateLayer: Bool { true }
    override func updateLayer() {}
    override func viewDidChangeBackingProperties() {
        super.viewDidChangeBackingProperties()
        metalLayer?.contentsScale = EdgeGlowView.pixelsPerPoint
        updateDrawableSize()
    }
    override func layout() { super.layout(); updateDrawableSize() }

    private func updateDrawableSize() {
        let s = EdgeGlowView.pixelsPerPoint
        metalLayer?.drawableSize = CGSize(width: max(1, bounds.width * s), height: max(1, bounds.height * s))
    }

    func startAnimating() {
        guard link == nil, pipeline != nil else { return }
        let l = displayLink(target: self, selector: #selector(tick))
        l.add(to: .main, forMode: .common)
        link = l
    }
    func stopAnimating() { link?.invalidate(); link = nil }

    @objc private func tick(_ sender: CADisplayLink) { render() }

    private func buildPipeline() {
        guard let device else { NSLog("Flowline glow: no Metal device"); return }
        do {
            let lib = try device.makeLibrary(source: EdgeGlowView.shaderSource, options: nil)
            let desc = MTLRenderPipelineDescriptor()
            desc.vertexFunction = lib.makeFunction(name: "glowVertex")
            desc.fragmentFunction = lib.makeFunction(name: "glowFragment")
            desc.colorAttachments[0].pixelFormat = .bgra8Unorm
            pipeline = try device.makeRenderPipelineState(descriptor: desc)
        } catch {
            NSLog("Flowline glow: shader failed — %@", "\(error)")
        }
    }

    private func render() {
        guard let layer = metalLayer, let queue, let pipeline, let drawable = layer.nextDrawable(),
              let cmd = queue.makeCommandBuffer() else { return }
        let pass = MTLRenderPassDescriptor()
        pass.colorAttachments[0].texture = drawable.texture
        pass.colorAttachments[0].loadAction = .clear
        pass.colorAttachments[0].storeAction = .store
        pass.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: pass) else { return }
        var u = Uniforms(time: Float(CACurrentMediaTime() - start),
                         resolution: SIMD2(Float(bounds.width), Float(bounds.height)),
                         hue: hue, thickness: thickness,
                         drawable: SIMD2(Float(layer.drawableSize.width), Float(layer.drawableSize.height)))
        enc.setRenderPipelineState(pipeline)
        enc.setFragmentBytes(&u, length: MemoryLayout<Uniforms>.stride, index: 0)
        enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        enc.endEncoding()
        cmd.present(drawable)
        cmd.commit()
    }

    /// Straight port of design/edge-glow.frag (GLSL ES → MSL). Keep the two in step.
    static let shaderSource = """
    #include <metal_stdlib>
    using namespace metal;

    struct Uniforms { float time; float2 resolution; float hue; float thickness; float2 drawable; };
    struct VOut { float4 pos [[position]]; };

    vertex VOut glowVertex(uint vid [[vertex_id]]) {
        float2 v = float2((vid << 1) & 2, vid & 2);          // one triangle covering the layer
        VOut o; o.pos = float4(v * 2.0 - 1.0, 0.0, 1.0); return o;
    }

    static float3 rgb2yiq(float3 c) {
        return float3(dot(c, float3(0.299, 0.587, 0.114)), dot(c, float3(0.596, -0.274, -0.322)), dot(c, float3(0.211, -0.523, 0.312)));
    }
    static float3 yiq2rgb(float3 c) {
        return float3(c.x + 0.956 * c.y + 0.621 * c.z, c.x - 0.272 * c.y - 0.647 * c.z, c.x - 1.106 * c.y + 1.703 * c.z);
    }
    static float3 adjustHue(float3 color, float hueDeg) {
        float h = hueDeg * M_PI_F / 180.0;
        float3 yiq = rgb2yiq(color);
        float ca = cos(h), sa = sin(h);
        yiq.yz = float2(yiq.y * ca - yiq.z * sa, yiq.y * sa + yiq.z * ca);
        return yiq2rgb(yiq);
    }
    static float3 hash33(float3 p3) {
        p3 = fract(p3 * float3(0.1031, 0.11369, 0.13787));
        p3 += dot(p3, p3.yxz + 19.19);
        return -1.0 + 2.0 * fract(float3(p3.x + p3.y, p3.x + p3.z, p3.y + p3.z) * p3.zyx);
    }
    static float snoise3(float3 p) {
        const float K1 = 0.333333333;
        const float K2 = 0.166666667;
        float3 i = floor(p + (p.x + p.y + p.z) * K1);
        float3 d0 = p - (i - (i.x + i.y + i.z) * K2);
        float3 e = step(float3(0.0), d0 - d0.yzx);
        float3 i1 = e * (1.0 - e.zxy);
        float3 i2 = 1.0 - e.zxy * (1.0 - e);
        float3 d1 = d0 - (i1 - K2);
        float3 d2 = d0 - (i2 - K1);
        float3 d3 = d0 - 0.5;
        float4 h = max(0.6 - float4(dot(d0, d0), dot(d1, d1), dot(d2, d2), dot(d3, d3)), 0.0);
        float4 n = h * h * h * h * float4(dot(d0, hash33(i)), dot(d1, hash33(i + i1)), dot(d2, hash33(i + i2)), dot(d3, hash33(i + 1.0)));
        return dot(float4(31.316), n);
    }
    static float light1(float intensity, float attenuation, float dist) { return intensity / (1.0 + dist * attenuation); }
    static float light2(float intensity, float attenuation, float dist) { return intensity / (1.0 + dist * dist * attenuation); }

    constant float3 baseColor0 = float3(0.239, 0.353, 1.0);   // blue
    constant float3 baseColor1 = float3(0.616, 0.0, 1.0);     // purple
    constant float3 baseColor2 = float3(1.0, 0.373, 0.122);   // orange

    fragment float4 glowFragment(VOut in [[stage_in]], constant Uniforms& u [[buffer(0)]]) {
        float2 uv = in.pos.xy / u.drawable;
        uv.y = 1.0 - uv.y;                                     // GL-style origin, as in the reference
        float2 p = uv * u.resolution;                          // position in points
        float2 h = u.resolution * 0.5;
        float2 q = abs(p - h) - h;
        float sd = -max(q.x, q.y);                             // distance inward from the nearest edge (>= 0 inside)

        // The glow is zero past 1.4 × the deepest possible thickness (1.51 × base): skip the noise in the interior.
        if (sd > u.thickness * 2.2) { return float4(0.0); }

        float2 k = p / u.resolution.y;
        float n0 = snoise3(float3(k * 1.6, u.time * 0.35)) * 0.5 + 0.5;
        float n1 = snoise3(float3(k * 4.0 + 7.0, u.time * 0.6)) * 0.5 + 0.5;
        float pulse = sin(u.time * 1.5) * 0.06;
        float th = u.thickness * (0.65 + 0.6 * n0 + 0.2 * n1 + pulse);   // wavy glow depth

        float d = sd / th;                                                // 0 at the edge → 1 at the inner boundary
        float glow = light1(1.0, 6.0, d) * smoothstep(1.4, 0.0, d);

        float ang = atan2(p.y - h.y, p.x - h.x);                           // bright point orbiting the perimeter
        float cl = cos(ang - u.time * 0.8) * 0.5 + 0.5;
        float hi = light2(1.2, 3.0, (1.0 - cl) * 3.0) * smoothstep(1.0, 0.0, d);

        float3 col = mix(adjustHue(baseColor1, u.hue), adjustHue(baseColor2, u.hue), cl);
        col = mix(col, adjustHue(baseColor0, u.hue), n0);
        col = col * glow + float3(0.6) * hi * glow;
        col = clamp(col, 0.0, 1.0);
        float alpha = max(max(col.r, col.g), col.b);
        return float4(col, alpha);                                         // premultiplied
    }
    """
}
