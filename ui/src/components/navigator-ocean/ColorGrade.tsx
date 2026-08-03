import { useMemo } from "react";
import { BlendFunction, Effect } from "postprocessing";
import { Uniform } from "three";

const fragmentShader = /* glsl */ `
  uniform float uAmount;

  void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
    vec3 c0 = inputColor.rgb;
    vec3 c = c0;
    float l = dot(c0, vec3(0.299, 0.587, 0.114));

    vec3 shadowTint = vec3(0.014, 0.075, 0.09);
    vec3 highTint = vec3(0.14, 0.075, 0.02);
    float shadowMask = 1.0 - smoothstep(0.05, 0.38, l);
    float highMask = smoothstep(0.55, 0.92, l);
    vec3 tint = shadowTint * shadowMask + highTint * highMask;
    float warm = clamp((c0.r - c0.b) * 3.0, 0.0, 1.0);
    tint = mix(tint, highTint * highMask, warm);
    c += tint;

    vec3 sCurve = c * c * (3.0 - 2.0 * c);
    c = mix(c, sCurve, 0.16);
    float gray = dot(c, vec3(0.299, 0.587, 0.114));
    c = mix(vec3(gray), c, 1.16);

    float protect = smoothstep(0.55, 0.92, l);
    c = mix(c, c0, protect);
    c = mix(c0, c, uAmount);
    outputColor = vec4(clamp(c, 0.0, 1.0), inputColor.a);
  }
`;

class ColorGradeEffect extends Effect {
  constructor(amount: number) {
    super("NavigatorOceanColorGrade", fragmentShader, {
      blendFunction: BlendFunction.NORMAL,
      uniforms: new Map([["uAmount", new Uniform(amount)]]),
    });
  }
}

export type ColorGradeProps = Readonly<{
  /** Current host-owned camera/zoom transition, clamped to [0, 1]. */
  zoomT: number;
  /** Full-strength grade amount in perspective views. */
  amount?: number;
}>;

export function ColorGrade({ zoomT, amount = 0.6 }: ColorGradeProps) {
  const effect = useMemo(() => new ColorGradeEffect(amount), [amount]);
  const fade = 1 - Math.min(1, Math.max(0, zoomT) / 0.85);
  const amountUniform = effect.uniforms.get("uAmount");
  if (amountUniform) amountUniform.value = amount * fade;

  return <primitive object={effect} dispose={null} />;
}

export default ColorGrade;
