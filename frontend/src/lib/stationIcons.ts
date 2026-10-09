/**
 * The station and elevator icons, drawn pixel by pixel into RGBA buffers for
 * map.addImage. No canvas, fonts or image files: the page loads nothing new
 * (the Content-Security-Policy is unchanged) and node --test can look at the
 * pixels.
 *
 * A station is a pie of its lines' colours, one equal wedge per line from
 * twelve o'clock clockwise, split by thin white lines and ringed in near
 * black. The ring is what keeps the pale wedges (Yellow, Silver) apart from
 * the light base map and from each other.
 */

export interface Raster {
  width: number;
  height: number;
  data: Uint8Array;
  pixelRatio: number;
}

export const OUTLINE = "#1f2937";
const SEPARATOR = "#ffffff";
/** The station icon's diameter in CSS pixels at icon-size 1. */
export const STATION_ICON_PX = 20;
export const ELEVATOR_ICON_PX = 16;
const SAMPLES = 4; // per pixel side: 16 samples, for smooth edges

export type Rgb = [number, number, number];

export function hexToRgb(hex: string): Rgb {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a #rrggbb colour: ${hex}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Fill a buffer by asking `colourAt` for each sub-sample; null is transparent. */
export function rasterise(
  size: number,
  pixelRatio: number,
  colourAt: (x: number, y: number) => Rgb | null,
): Raster {
  const data = new Uint8Array(size * size * 4);
  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let hits = 0;
      for (let sy = 0; sy < SAMPLES; sy += 1) {
        for (let sx = 0; sx < SAMPLES; sx += 1) {
          const c = colourAt(px + (sx + 0.5) / SAMPLES, py + (sy + 0.5) / SAMPLES);
          if (!c) continue;
          r += c[0];
          g += c[1];
          b += c[2];
          hits += 1;
        }
      }
      if (hits === 0) continue;
      const i = (py * size + px) * 4;
      data[i] = Math.round(r / hits);
      data[i + 1] = Math.round(g / hits);
      data[i + 2] = Math.round(b / hits);
      data[i + 3] = Math.round((255 * hits) / (SAMPLES * SAMPLES));
    }
  }
  return { width: size, height: size, data, pixelRatio };
}

/**
 * A station's icon: a circle (Metro) or a square (a MARC-only station) cut
 * into one wedge per colour.
 */
export function stationIcon(
  colours: readonly string[],
  shape: "circle" | "square",
  pixelRatio = 2,
  cssSize = STATION_ICON_PX,
): Raster {
  if (colours.length === 0) throw new Error("a station icon needs at least one colour");
  const rgb = colours.map(hexToRgb);
  const outline = hexToRgb(OUTLINE);
  const separator = hexToRgb(SEPARATOR);
  const size = Math.round(cssSize * pixelRatio);
  const centre = size / 2;
  const radius = shape === "circle" ? size / 2 : size * 0.43;
  const ring = 1.5 * pixelRatio;
  const gap = 0.5 * pixelRatio; // half a separator's width
  const wedge = (2 * Math.PI) / rgb.length;
  return rasterise(size, pixelRatio, (x, y) => {
    const dx = x - centre;
    const dy = y - centre;
    const distance = shape === "circle" ? Math.hypot(dx, dy) : Math.max(Math.abs(dx), Math.abs(dy));
    if (distance > radius) return null;
    if (distance > radius - ring) return outline;
    if (rgb.length === 1) return rgb[0];
    // Clockwise from twelve o'clock (screen y points down).
    let angle = Math.atan2(dx, -dy);
    if (angle < 0) angle += 2 * Math.PI;
    for (let k = 0; k < rgb.length; k += 1) {
      const theta = k * wedge;
      const along = dx * Math.sin(theta) - dy * Math.cos(theta);
      const across = Math.abs(dx * Math.cos(theta) + dy * Math.sin(theta));
      if (along > 0 && across < gap) return separator;
    }
    return rgb[Math.min(rgb.length - 1, Math.floor(angle / wedge))];
  });
}

function insideTriangle(x: number, y: number, a: number[], b: number[], c: number[]): boolean {
  const side = (p: number[], q: number[]) => (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]);
  const s1 = side(a, b);
  const s2 = side(b, c);
  const s3 = side(c, a);
  return (s1 >= 0 && s2 >= 0 && s3 >= 0) || (s1 <= 0 && s2 <= 0 && s3 <= 0);
}

/** An elevator: the lift sign, white up and down arrows on a near-black square with a white edge. */
export function elevatorIcon(pixelRatio = 2, cssSize = ELEVATOR_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const dark = hexToRgb(OUTLINE);
  const white = hexToRgb(SEPARATOR);
  const edge = 1 * pixelRatio;
  const c = size / 2;
  const w = size * 0.2;
  const up = [
    [c, size * 0.16],
    [c - w, size * 0.44],
    [c + w, size * 0.44],
  ];
  const down = [
    [c, size * 0.84],
    [c - w, size * 0.56],
    [c + w, size * 0.56],
  ];
  return rasterise(size, pixelRatio, (x, y) => {
    if (x < edge || y < edge || x > size - edge || y > size - edge) return white;
    if (insideTriangle(x, y, up[0], up[1], up[2]) || insideTriangle(x, y, down[0], down[1], down[2])) return white;
    return dark;
  });
}
