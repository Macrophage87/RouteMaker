/**
 * Colour-vision simulation and colour difference, for the tests that hold a
 * stress palette to "still apart for everyone" (stressContrast.test.ts). Not
 * shipped: nothing under src/ but a test imports it.
 *
 * - Simulation: Machado, Oliveira and Fernandes (2009), severity 1.0, applied
 *   to linear RGB, then back to sRGB. Severity 1.0 is the full deficiency, the
 *   hardest case; a milder one is easier.
 * - Difference: CIEDE2000 (Sharma, Wu and Dalal's reference formulation), on
 *   CIELAB under D65.
 *
 * A port of the measuring script the palette was chosen with (the Python
 * reference in the task's scratchpad, cvd.py); colourVision.test.ts checks
 * this port against published values.
 */

export type Vision = "normal" | "protan" | "deutan" | "tritan";
export const VISIONS: readonly Vision[] = ["normal", "protan", "deutan", "tritan"];

const MACHADO: Record<Exclude<Vision, "normal">, number[][]> = {
  protan: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deutan: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
  tritan: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
};

const toLinear = (c: number): number => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};

const toGamma = (v: number): number => {
  const c = Math.min(Math.max(v, 0), 1);
  return Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055));
};

const channels = (hex: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

/** What a viewer with `vision` sees of a colour, as a hex colour. */
export function simulate(hex: string, vision: Vision): string {
  if (vision === "normal") return hex.toLowerCase();
  const lin = channels(hex).map(toLinear);
  const m = MACHADO[vision];
  const out = m.map((row) => toGamma(row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2]));
  return `#${out.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

/** CIELAB (D65) of a hex colour. */
export function lab(hex: string): [number, number, number] {
  const [r, g, b] = channels(hex).map(toLinear);
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
}

const rad = (deg: number) => (deg * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/** CIEDE2000 between two hex colours. */
export function deltaE2000(a: string, b: string): number {
  return deltaE2000Lab(lab(a), lab(b));
}

/** CIEDE2000 between two CIELAB colours (the form Sharma, Wu and Dalal publish test pairs in). */
export function deltaE2000Lab(first: readonly [number, number, number], second: readonly [number, number, number]): number {
  const [L1, a1, b1] = first;
  const [L2, a2, b2] = second;
  const C1 = Math.hypot(a1, b1);
  const C2 = Math.hypot(a2, b2);
  const Cb = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
  const a1p = (1 + G) * a1;
  const a2p = (1 + G) * a2;
  const C1p = Math.hypot(a1p, b1);
  const C2p = Math.hypot(a2p, b2);
  const h1 = (deg(Math.atan2(b1, a1p)) + 360) % 360;
  const h2 = (deg(Math.atan2(b2, a2p)) + 360) % 360;
  const dL = L2 - L1;
  const dC = C2p - C1p;
  let dh = 0;
  if (C1p * C2p !== 0) {
    dh = Math.abs(h2 - h1) <= 180 ? h2 - h1 : h2 > h1 ? h2 - h1 - 360 : h2 - h1 + 360;
  }
  const dH = 2 * Math.sqrt(C1p * C2p) * Math.sin(rad(dh / 2));
  const Lb = (L1 + L2) / 2;
  const Cbp = (C1p + C2p) / 2;
  let hb: number;
  if (C1p * C2p === 0) hb = h1 + h2;
  else if (Math.abs(h1 - h2) <= 180) hb = (h1 + h2) / 2;
  else hb = h1 + h2 < 360 ? (h1 + h2 + 360) / 2 : (h1 + h2 - 360) / 2;
  const T =
    1 -
    0.17 * Math.cos(rad(hb - 30)) +
    0.24 * Math.cos(rad(2 * hb)) +
    0.32 * Math.cos(rad(3 * hb + 6)) -
    0.2 * Math.cos(rad(4 * hb - 63));
  const SL = 1 + (0.015 * (Lb - 50) ** 2) / Math.sqrt(20 + (Lb - 50) ** 2);
  const SC = 1 + 0.045 * Cbp;
  const SH = 1 + 0.015 * Cbp * T;
  const RT = -2 * Math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) * Math.sin(rad(60 * Math.exp(-(((hb - 275) / 25) ** 2))));
  return Math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * (dC / SC) * (dH / SH));
}

/** ΔE2000 between each tier and the next, as seen with `vision`. */
export function adjacentDeltas(colours: readonly string[], vision: Vision): number[] {
  const seen = colours.map((c) => simulate(c, vision));
  return seen.slice(1).map((c, i) => deltaE2000(seen[i], c));
}

/** The smallest ΔE2000 between any two of the colours, as seen with `vision`. */
export function closestPair(colours: readonly string[], vision: Vision): { delta: number; pair: [number, number] } {
  const seen = colours.map((c) => simulate(c, vision));
  let best = { delta: Infinity, pair: [0, 1] as [number, number] };
  for (let i = 0; i < seen.length; i += 1) {
    for (let j = i + 1; j < seen.length; j += 1) {
      const delta = deltaE2000(seen[i], seen[j]);
      if (delta < best.delta) best = { delta, pair: [i, j] };
    }
  }
  return best;
}
