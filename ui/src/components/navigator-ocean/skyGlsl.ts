/**
 * Shared procedural dusk atmosphere used by both the visible sky and the
 * ocean-reflection shader. Keeping one source prevents the two palettes and
 * sun directions from drifting apart.
 */
export const SKY_GLSL = /* glsl */ `
  vec3 bpSunDir() { return normalize(vec3(0.14, 0.085, -1.0)); }

  float bpHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

  float bpVnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = bpHash(i);
    float b = bpHash(i + vec2(1.0, 0.0));
    float c = bpHash(i + vec2(0.0, 1.0));
    float d = bpHash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
  }

  float bpFbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 5; i++) {
      value += amplitude * bpVnoise(p);
      p *= 2.03;
      amplitude *= 0.5;
    }
    return value;
  }

  float bpClouds(vec3 dir, float time, out vec3 cloudColor) {
    cloudColor = vec3(0.0);
    if (dir.y < 0.015) return 0.0;

    vec2 uv = dir.xz / (dir.y + 0.22);
    uv *= 1.25;
    vec2 drift = vec2(time * 0.012, time * 0.004);

    float base = bpFbm(uv * 0.6 + drift);
    float detail = bpFbm(uv * 1.6 - drift * 1.7);
    float density = base * 0.72 + detail * 0.28;
    float cover = smoothstep(0.52, 0.86, density);
    float horizonFade = smoothstep(0.02, 0.14, dir.y)
      * (1.0 - smoothstep(0.55, 0.95, dir.y));
    cover *= horizonFade;

    vec3 sunDirection = bpSunDir();
    float sunAmount = pow(max(dot(normalize(dir), sunDirection), 0.0) * 0.5 + 0.5, 3.0);
    vec3 warmLight = vec3(1.0, 0.62, 0.34);
    vec3 coolTop = vec3(0.30, 0.36, 0.48);
    float edge = smoothstep(0.86, 0.52, density);
    cloudColor = mix(coolTop, warmLight, sunAmount * 0.85 + edge * 0.25);
    return cover;
  }

  vec3 bpSkyColor(vec3 dir, float time) {
    vec3 zenith = vec3(0.015, 0.035, 0.085);
    vec3 middle = vec3(0.05, 0.11, 0.21);
    vec3 horizon = vec3(0.08, 0.13, 0.23);
    vec3 duskWarm = vec3(0.90, 0.45, 0.20);
    vec3 sunColor = vec3(1.0, 0.66, 0.34);
    float height = dir.y;

    vec3 color = mix(horizon, middle, smoothstep(-0.02, 0.30, height));
    color = mix(color, zenith, smoothstep(0.18, 0.85, height));

    vec3 sunDirection = bpSunDir();
    float sunDot = max(dot(normalize(dir), sunDirection), 0.0);
    float horizonBand = exp(-abs(height) * 4.5);
    float towardSun = pow(sunDot * 0.5 + 0.5, 2.2);
    color = mix(color, duskWarm, clamp(horizonBand * towardSun, 0.0, 1.0));
    color += duskWarm * exp(-abs(height) * 12.0) * 0.18;

    vec3 cloudColor;
    float cover = bpClouds(dir, time, cloudColor) * 0.9;
    color = mix(color, cloudColor, cover);

    float disk = pow(sunDot, 700.0);
    float halo = pow(sunDot, 11.0);
    color += sunColor * disk * 3.0 * (1.0 - cover * 0.6);
    color += sunColor * halo * 0.45;
    return color;
  }

  float bpStars(vec3 dir, float time) {
    if (dir.y < 0.12) return 0.0;
    vec2 uv = dir.xz / (dir.y + 0.35) * 14.0;
    vec2 grid = floor(uv);
    float randomValue = bpHash(grid);
    float star = smoothstep(0.988, 0.9995, randomValue);
    float twinkle = 0.6 + 0.4 * sin(time * 2.5 + randomValue * 40.0);
    return star * twinkle * smoothstep(0.12, 0.5, dir.y);
  }
`;
