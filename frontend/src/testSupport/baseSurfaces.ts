// The light base map's surfaces a trail can lie over (as stressContrast.test.ts reads them), for the
// mountain-bike layer's 3:1 checks (mtbTrail.test.ts, mtbLevels.test.ts).
import { LIGHT } from "@protomaps/basemaps";

export function baseSurfaces(): Record<string, string> {
  const out: Record<string, string> = {};
  const SURFACE = /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|other|minor|link|major$|highway$|bridges_)/;
  for (const [key, value] of Object.entries(LIGHT)) {
    if (typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) && SURFACE.test(key) && !key.includes("casing")) out[key] = value.toLowerCase();
  }
  for (const [key, value] of Object.entries((LIGHT as { landcover?: Record<string, string> }).landcover ?? {})) {
    const m = value.match(/^rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)/);
    if (m) out[`landcover.${key}`] = `#${m.slice(1, 4).map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;
  }
  return out;
}
