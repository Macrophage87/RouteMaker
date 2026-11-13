import { useEffect, useId, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { RouteResponse } from "./lib/api.ts";
import type { Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import type { PresetId } from "./lib/presets.ts";
import {
  CHECK_ABOUT,
  CHECK_FAILED,
  CHECK_HEADING,
  CHECK_NONE,
  CHECK_NO_WAY,
  CHECK_PLANNING,
  CHECK_USE,
  calmerLine,
  checkedSaid,
  planCalmerWay,
  stretchEnds,
  stretchLine,
  worstStretches,
  type CalmerWay,
  type Planner,
  type WorstStretch,
} from "./lib/worstStretches.ts";
import { showCalmerWays } from "./lib/calmerWayLayer.ts";
import { InfoButton } from "./SettingRow.tsx";
import { t } from "./lib/i18n.ts";

export interface CheckRouteProps {
  /** The route shown, which follows an opened file (`follows_file`). */
  route: RouteResponse;
  preset: PresetId;
  dials: Dials;
  getMap: () => MapLibreMap | null;
  /** Plans a calmer way (App: requestRoute with the route alone). */
  plan: Planner;
  /** Use this way: the calmer way into the file's line (App); absent where the file has no line to splice. */
  onUse?: (stretch: WorstStretch, way: LonLat[]) => void;
}

/**
 * The map's padding clear of the page's panels (each open `aside`, and the route section where it stands apart on a computer), so the stretch shown is not under one: on a phone the
 * sheet at the bottom, on a computer the planner on one side and the route on the other, as GpxPanel's fit does.
 */
// The margins (60 px top and bottom, 40 px at the sides, 30 px over a panel's edge), the zoom held to 17 and the
// 0.4 s move are our defaults, unmeasured, near GpxPanel's own fit.
function clearOfPanels(): { top: number; bottom: number; left: number; right: number } {
  const padding = { top: 60, bottom: 60, left: 40, right: 40 };
  const width = window.innerWidth;
  const narrow = window.matchMedia("(max-width: 720px)").matches;
  for (const aside of document.querySelectorAll("aside, .route-section")) {
    const r = aside.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (narrow) padding.bottom = Math.max(padding.bottom, window.innerHeight - r.top + 30);
    else if (r.left + r.width / 2 < width / 2) padding.left = Math.max(padding.left, r.right + 40);
    else padding.right = Math.max(padding.right, width - r.left + 40);
  }
  return padding;
}

/**
 * Check a route (lib/worstStretches.ts): an opened file's busiest stretches, worst first, each with a calmer way round
 * and Use this way. Plan only, on a route that follows an opened file; it opens with the route, with no control of
 * its own but each stretch's Use this way (the owner's pick, 2026-11-13).
 */
export function CheckRoute({ route, preset, dials, getMap, plan, onUse }: CheckRouteProps) {
  const [stretches, setStretches] = useState<WorstStretch[]>([]);
  const [ways, setWays] = useState<(CalmerWay | null)[]>([]);
  const [about, setAbout] = useState(false);
  const aboutId = useId();
  // The plan and the dials are read when the route arrives, not followed: a new route plans the calmer ways again.
  const asked = useRef({ preset, dials, plan });
  asked.current = { preset, dials, plan };

  useEffect(() => {
    const found = worstStretches(route);
    setStretches(found);
    setWays(found.map(() => null));
    let live = true;
    void (async () => {
      // One after another: three at once could meet the planner's per-client limit.
      for (let i = 0; i < found.length; i += 1) {
        const { preset: p, dials: d, plan: run } = asked.current;
        const way = await planCalmerWay(route, found[i], p, d, run).catch((): CalmerWay => ({ kind: "failed" }));
        if (!live) return;
        setWays((was) => was.map((w, k) => (k === i ? way : w)));
      }
    })();
    return () => {
      live = false;
    };
  }, [route]);

  // The calmer ways found, drawn on the map while the list shows.
  useEffect(() => {
    const lines = ways.flatMap((w) => (w?.kind === "found" ? [w.line] : []));
    const map = getMap();
    if (map) showCalmerWays(map, lines);
  }, [ways, getMap]);
  useEffect(
    () => () => {
      const map = getMap();
      if (map) showCalmerWays(map, []);
    },
    [getMap],
  );

  const show = (stretch: WorstStretch, way: CalmerWay | null) => {
    const map = getMap();
    if (!map) return;
    const line = [...stretchEnds(route, stretch).line, ...(way?.kind === "found" ? way.line : [])];
    let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const [lon, lat] of line) {
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
    if (Number.isFinite(west)) map.fitBounds([west, south, east, north], { padding: clearOfPanels(), maxZoom: 17, duration: 400 });
  };

  return (
    <section className="check-route" aria-labelledby="check-route-heading">
      <div className="setting-line">
        <h3 id="check-route-heading">{CHECK_HEADING}</h3>
        <InfoButton open={about} onToggle={() => setAbout((was) => !was)} controls={aboutId} about={t("busiest stretches")} />
      </div>
      <p className="hint setting-info" id={aboutId} hidden={!about}>
        {CHECK_ABOUT}
      </p>
      {/* One line for a screen reader once every calmer way is looked for, not one per row (the review's a11y finding). */}
      <p className="visually-hidden" role="status">
        {ways.every((w) => w !== null) ? checkedSaid(stretches.length, ways.filter((w) => w?.kind === "found").length) : ""}
      </p>
      {stretches.length === 0 ? (
        <p className="hint check-none">{CHECK_NONE}</p>
      ) : (
        <ol className="check-list">
          {stretches.map((stretch, i) => {
            const way = ways[i] ?? null;
            return (
              <li key={`${stretch.fromM}-${stretch.toM}`}>
                {/* The stretch's words are the button: one press shows it, and its calmer way, on the map. */}
                <button type="button" className="link check-stretch" onClick={() => show(stretch, way)}>
                  {stretchLine(stretch)}
                </button>
                <p className={way === null ? "loading check-way" : "hint check-way"}>
                  {way === null ? CHECK_PLANNING : way.kind === "found" ? calmerLine(way) : way.kind === "none" ? CHECK_NO_WAY : CHECK_FAILED}
                </p>
                {way?.kind === "found" && onUse && (
                  <button type="button" className="secondary check-use" onClick={() => onUse(stretch, way.line)}>
                    {CHECK_USE}
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
