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

/** A closed station's fill, ring and strike: grey, so the lines' colours do not read as running. */
export const CLOSED_FILL = "#d1d5db";
export const CLOSED_RING = "#6b7280";
export const CLOSED_STRIKE = "#1f2937";

/**
 * A closed station: its usual shape in grey with a near-black stroke from corner to corner (top right
 * to bottom left) cased in white, so it reads as struck through on the light and dark base maps alike
 * and without colour.
 */
export function closedStationIcon(shape: "circle" | "square", pixelRatio = 2, cssSize = STATION_ICON_PX): Raster {
  const fill = hexToRgb(CLOSED_FILL);
  const ring = hexToRgb(CLOSED_RING);
  const strike = hexToRgb(CLOSED_STRIKE);
  const white = hexToRgb(SEPARATOR);
  const size = Math.round(cssSize * pixelRatio);
  const centre = size / 2;
  const radius = shape === "circle" ? size / 2 : size * 0.43;
  const ringWidth = 1.5 * pixelRatio;
  const half = 1.25 * pixelRatio;
  const casing = half + 1 * pixelRatio;
  return rasterise(size, pixelRatio, (x, y) => {
    const dx = x - centre;
    const dy = y - centre;
    const distance = shape === "circle" ? Math.hypot(dx, dy) : Math.max(Math.abs(dx), Math.abs(dy));
    // The stroke runs past the shape a little, to the icon's edge.
    const across = Math.abs(dx + dy) / Math.SQRT2;
    const along = Math.abs(dx - dy) / Math.SQRT2;
    if (along <= size / 2 - 0.5) {
      if (across <= half) return strike;
      if (across <= casing && distance <= radius) return white;
    }
    if (distance > radius) return null;
    if (distance > radius - ringWidth) return ring;
    return fill;
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
  return rasterise(size, pixelRatio, elevatorAt(size, pixelRatio));
}

function elevatorAt(size: number, pixelRatio: number): (x: number, y: number) => Rgb {
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
  return (x, y) => {
    if (x < edge || y < edge || x > size - edge || y > size - edge) return white;
    if (insideTriangle(x, y, up[0], up[1], up[2]) || insideTriangle(x, y, down[0], down[1], down[2])) return white;
    return dark;
  };
}

/** The badges on a station with a WMATA alert or an elevator out (the owner, 2026-10-18), in CSS pixels. */
export const BADGE_ICON_PX = 13;
export const ALERT_FILL = "#f59e0b";
export const OUT_STRIKE = "#dc2626";

/**
 * A notice: a near-black "!" in an amber triangle with a near-black edge, the usual warning sign. A shape
 * as well as a colour; the station's card says the alert in words.
 */
export function alertBadgeIcon(pixelRatio = 2, cssSize = BADGE_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const dark = hexToRgb(OUTLINE);
  const amber = hexToRgb(ALERT_FILL);
  const edge = 1.2 * pixelRatio;
  const outer = [
    [size / 2, 0.5],
    [0.5, size - 0.5],
    [size - 0.5, size - 0.5],
  ];
  const inner = [
    [size / 2, edge * 2.2],
    [edge * 1.3, size - edge],
    [size - edge * 1.3, size - edge],
  ];
  const c = size / 2;
  const bar = size * 0.07;
  return rasterise(size, pixelRatio, (x, y) => {
    if (!insideTriangle(x, y, outer[0], outer[1], outer[2])) return null;
    if (!insideTriangle(x, y, inner[0], inner[1], inner[2])) return dark;
    if (Math.abs(x - c) <= bar && y >= size * 0.36 && y <= size * 0.68) return dark;
    if (Math.hypot(x - c, y - size * 0.8) <= bar * 1.2) return dark;
    return amber;
  });
}

/** An elevator out: the lift sign crossed out corner to corner in red, cased in white so it reads on the dark square. */
export function elevatorOutIcon(pixelRatio = 2, cssSize = BADGE_ICON_PX + 1): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const lift = elevatorAt(size, pixelRatio);
  const red = hexToRgb(OUT_STRIKE);
  const white = hexToRgb(SEPARATOR);
  const half = 1.1 * pixelRatio;
  const casing = half + 0.8 * pixelRatio;
  return rasterise(size, pixelRatio, (x, y) => {
    // From top left to bottom right, as a "no" sign's bar runs.
    const across = Math.abs(x - y) / Math.SQRT2;
    if (across <= half) return red;
    if (across <= casing) return white;
    return lift(x, y);
  });
}
