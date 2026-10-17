/**
 * A line as Valhalla's encoded polyline at precision 6 (the inverse of the API's `routing.decode_polyline6`), the
 * compact form POST /api/route takes an opened file's line to follow in (`follow`, core/follow.py).
 */
import type { LonLat } from "./geo.ts";

export function encodePolyline6(line: readonly LonLat[]): string {
  let out = "";
  let lat = 0;
  let lon = 0;
  for (const [x, y] of line) {
    const nextLat = Math.round(y * 1e6);
    const nextLon = Math.round(x * 1e6);
    for (let delta of [nextLat - lat, nextLon - lon]) {
      delta = delta < 0 ? ~(delta * 2) : delta * 2;
      while (delta >= 0x20) {
        out += String.fromCharCode((0x20 | (delta & 0x1f)) + 63);
        delta = Math.floor(delta / 32);
      }
      out += String.fromCharCode(delta + 63);
    }
    lat = nextLat;
    lon = nextLon;
  }
  return out;
}
