/**
 * GPX export as close to identical as possible (v0.7.0 plan, Stephen 2026-10-15 20:18 UTC): a route opened
 * from a GPX file and not edited downloads as the file it came from, byte for byte (its track points,
 * elevations and waypoint names unchanged). Edited, or planned here, the download is the line on screen:
 * every point, 6 decimals, with elevations (lib/gpx.ts writeGpx). A file whose closed stretches were
 * rerouted is written from its kept line: the file's own points (and elevations) outside the detours.
 */
import { CREATOR, writeGpx } from "./gpx.ts";
import type { LonLat } from "./geo.ts";
import type { Verbatim } from "./gpxPlan.ts";

export interface FileDownload {
  text: string;
  fileName: string;
}

/** A file name for the download: the file's own name where it has one, else "route.gpx". */
export function verbatimFileName(name: string | undefined): string {
  const base = (name ?? "").trim().replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80);
  return `${base || "route"}.gpx`;
}

/** The opened file's own line written as a GPX track: every point as kept, with its elevation where it had one. */
export function trackGpx(name: string, track: Verbatim["track"]): string {
  const geometry: LonLat[] = track.map((v) => [v[0], v[1]]);
  return writeGpx({
    name,
    description: `Route opened in ${CREATOR} from a GPX file.`,
    attribution: [],
    preset: "default",
    planPoints: [],
    geometry,
    elevations: track.map((v) => (v.length > 2 ? (v[2] as number) : null)),
  });
}

/**
 * The download for an opened file, or null when the route on screen is to be written instead (the plan was
 * edited, or nothing was opened). An unedited file is its own text; one rerouted round closures is its kept line.
 */
export function verbatimDownload(verbatim: Verbatim | undefined, edited: boolean, name: string | undefined): FileDownload | null {
  if (!verbatim || edited) return null;
  return {
    text: verbatim.text ?? trackGpx(name ?? "Route", verbatim.track),
    fileName: verbatimFileName(name),
  };
}

/** Save `text` as a file named `fileName` (the browser's download). */
export function downloadText(text: string, fileName: string): void {
  const blob = new Blob([text], { type: "application/gpx+xml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
