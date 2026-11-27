/**
 * The rider's GPS position in small print in a corner of the ride screen, so a screenshot sent with a bug report
 * says exactly where it was taken (the owner, 2026-11-27: "a small watermark on ride screens that makes it easy to
 * look up the exact gps coordinates if shared"). Latitude, longitude to 5 decimals (about 1 m), the form a map's
 * search box takes as pasted. Beta builds only (App passes isBetaBuild): a screenshot posted publicly carries the
 * spot. Drawn on the phone from the ride's own fix; nothing is sent or kept. Hidden from screen readers, which
 * have Where am I?
 */
import type { ReactElement } from "react";
import type { LonLat } from "./lib/geo.ts";

/** "38.88712, -77.02341": latitude first, as map search boxes read it. */
export function gpsMarkText(point: LonLat): string {
  return `${point[1].toFixed(5)}, ${point[0].toFixed(5)}`;
}

/** `stale`: the GPS is weak or lost, so the point is the last one heard: shown with a "?" after it. */
export function GpsMark({ point, stale = false }: { point: LonLat | null; stale?: boolean }): ReactElement | null {
  if (!point || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) return null;
  return (
    <p className="ride-gps-mark" aria-hidden="true" translate="no">
      {gpsMarkText(point)}
      {stale ? " ?" : ""}
    </p>
  );
}
