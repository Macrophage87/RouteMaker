import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import { writeGpx } from "./lib/gpx.ts";
import { REFINE_ROUNDS, nextRefinement, type ImportedPlan } from "./lib/gpxPlan.ts";
import { gpxWorker, importGpx } from "./lib/gpxImport.ts";
import { exportFileName, exportOf, fidelityNotice, importSentences } from "./lib/gpxText.ts";
import { showReference } from "./lib/referenceLayer.ts";
import { fidelity } from "./lib/trackMatch.ts";

interface Props {
  /** The route on screen, or null. */
  route: RouteResponse | null;
  /** The points that route was planned through. */
  routedPoints: LonLat[];
  /** The plan's points now. */
  points: LonLat[];
  /** Where the planner is with them (App's status). */
  planStatus: "idle" | "loading" | "waiting" | "ok" | "error" | "confirm";
  /** The file opened last, until the plan is cleared. */
  imported: ImportedPlan | null;
  onImport: (plan: ImportedPlan) => void;
  /** Replace the plan's points with a closer fit to the opened track. */
  onRefine: (points: LonLat[]) => void;
  getMap: () => MapLibreMap | null;
}

/** Fitting an imported track: the points last set for it, and the rounds so far. */
interface Fit {
  points: LonLat[];
  rounds: number;
}

function samePoints(a: readonly LonLat[], b: readonly LonLat[]): boolean {
  return a.length === b.length && a.every((p, i) => p[0] === b[i][0] && p[1] === b[i][1]);
}

function bounds(line: readonly LonLat[]): [number, number, number, number] {
  let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [lon, lat] of line) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [west, south, east, north];
}

type Reading = { kind: "idle" } | { kind: "reading"; name: string } | { kind: "error"; message: string };

/**
 * Open and download GPX, signed out. Both happen in this browser: the opened
 * file is read here (gpxImport.ts) and the download is built here from the
 * route on screen (gpx.ts). Nothing is sent or saved.
 */
export function GpxPanel({ route, routedPoints, points, planStatus, imported, onImport, onRefine, getMap }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState<Reading>({ kind: "idle" });
  const [showTrack, setShowTrack] = useState(true);
  const [fit, setFit] = useState<Fit | null>(null);

  // An opened track is fitted in rounds (gpxPlan.ts, nextRefinement): when
  // the route for the fitted points arrives, points go where it missed the
  // track, and the planner routes again. It stops when the route follows
  // the track, the rounds or the points run out, or the rider changes the
  // plan themselves - their change is never overwritten.
  useEffect(() => {
    if (!fit) return;
    // A refusal ends it too: the rider has the error to act on, not a loop.
    if (!imported || !samePoints(points, fit.points) || planStatus === "error") {
      setFit(null);
      return;
    }
    if (!route || !samePoints(routedPoints, fit.points)) return;
    const next = nextRefinement(imported.reference, fit.points, route.geometry.coordinates, fit.rounds);
    if (!next) {
      setFit(null);
      return;
    }
    setFit({ points: next, rounds: fit.rounds + 1 });
    onRefine(next);
  }, [fit, imported, points, planStatus, route, routedPoints, onRefine]);

  // The file's own line, faint, under the route.
  const reference = imported && showTrack && imported.reference.length >= 2 ? imported.reference : null;
  useEffect(() => {
    const map = getMap();
    if (map) showReference(map, reference);
  }, [reference, getMap]);

  const match = useMemo(() => {
    if (!imported || imported.reference.length < 2 || !route || fit) return null;
    return fidelityNotice(fidelity(imported.reference, route.geometry.coordinates));
  }, [imported, route, fit]);

  const open = async (file: File) => {
    setReading({ kind: "reading", name: file.name });
    const outcome = await importGpx(file, typeof Worker === "function" ? gpxWorker : null);
    if (outcome.ok) {
      setReading({ kind: "idle" });
      setShowTrack(true);
      setFit(outcome.plan.source === "track" ? { points: outcome.plan.points, rounds: 0 } : null);
      onImport(outcome.plan);
      frame(outcome.plan);
    } else {
      setReading({ kind: "error", message: outcome.message });
    }
  };

  // An opened file is shown whole, beside the panel rather than under it.
  // MapView moves only when a route leaves the view, and a file opened over
  // a wider view would otherwise be a speck in it.
  const frame = (plan: ImportedPlan) => {
    const map = getMap();
    const line = plan.reference.length >= 2 ? plan.reference : plan.points;
    if (!map || line.length < 2) return;
    const panel = document.querySelector(".panel")?.getBoundingClientRect();
    const narrow = window.matchMedia("(max-width: 720px)").matches;
    const padding = narrow
      ? { top: 40, left: 30, right: 30, bottom: (panel?.height ?? 0) + 90 }
      : { top: 60, bottom: 60, right: 60, left: (panel?.right ?? 0) + 40 };
    const [west, south, east, north] = bounds(line);
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding, maxZoom: 15, duration: 600 },
    );
  };

  const download = () => {
    if (!route) return;
    const blob = new Blob([writeGpx(exportOf(route, routedPoints))], { type: "application/gpx+xml" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = exportFileName(route);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  return (
    <section aria-labelledby="gpx-heading" className="gpx">
      <h2 id="gpx-heading">GPX file</h2>
      <div className="actions">
        <button type="button" onClick={() => input.current?.click()} disabled={reading.kind === "reading"}>
          Open GPX…
        </button>
        <button type="button" onClick={download} disabled={!route}>
          Download GPX
        </button>
      </div>
      <input
        ref={input}
        type="file"
        accept=".gpx,application/gpx+xml"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          // The same file can be opened again after a change.
          event.target.value = "";
          if (file) void open(file);
        }}
      />
      <div role="status" aria-live="polite">
        {reading.kind === "reading" && <p className="loading">Reading {reading.name}…</p>}
        {reading.kind === "error" && (
          <p className="notice gpx-error">
            <strong>Can't open that file.</strong> {reading.message}
          </p>
        )}
        {reading.kind === "idle" && imported && (
          <div className="gpx-import">
            {importSentences(imported).map((sentence) => (
              <p key={sentence} className="hint">
                {sentence}
              </p>
            ))}
            {fit && ["loading", "waiting", "ok"].includes(planStatus) && (
              <p className="loading gpx-fitting">
                {fit.rounds === 0
                  ? "Routing the plan along the file's track…"
                  : `Adding points where the route left the track (round ${fit.rounds} of up to ${REFINE_ROUNDS})…`}
              </p>
            )}
            {match && <p className={match.warn ? "notice gpx-deviation" : "hint gpx-fidelity"}>{match.text}</p>}
          </div>
        )}
      </div>
      {imported && imported.reference.length >= 2 && (
        <label className="toggle">
          <input type="checkbox" checked={showTrack} onChange={(event) => setShowTrack(event.target.checked)} />
          Show the file's track on the map
        </label>
      )}
      <p className="hint">
        A file you open is read in this browser and never uploaded. The download is the route shown, with its
        credits: © OpenStreetMap contributors (ODbL) and the traffic and elevation sources.
      </p>
    </section>
  );
}
