import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import type { Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import type { PresetId } from "./lib/presets.ts";
import { showCalmerWays } from "./lib/calmerWayLayer.ts";
import {
  STRETCH_AVOID,
  STRETCH_CLEAR,
  STRETCH_FAILED,
  STRETCH_NO_WAY,
  STRETCH_PLANNING,
  asWorst,
  factsLine,
  planAround,
  stretchFacts,
  wayLine,
  whyAvoid,
  type WayRound,
} from "./lib/chartStretch.ts";
import { CHECK_USE, type Planner, type WorstStretch } from "./lib/worstStretches.ts";
import { t } from "./lib/i18n.ts";

export interface ChartStretchProps {
  route: RouteResponse;
  profile: RouteProfile;
  /** The stretch picked on the chart, in the route's metres. */
  fromM: number;
  toM: number;
  onClear: () => void;
  preset: PresetId;
  dials: Dials;
  plan: Planner;
  getMap: () => MapLibreMap | null;
  /** Use this way (App): absent where the plan cannot take one (a file it follows without its line). */
  onUse?: (stretch: WorstStretch, way: LonLat[]) => void;
}

/**
 * The stretch picked on Plan's route chart (lib/chartStretch.ts): its miles, climb and stress, and on a busy or steep
 * one, Try to avoid this stretch, which plans a way round, says what it costs and offers Use this way. Loaded on first
 * use, as Check a route is.
 */
export function ChartStretch({ route, profile, fromM, toM, onClear, preset, dials, plan, getMap, onUse }: ChartStretchProps) {
  const facts = useMemo(() => stretchFacts(route, profile, fromM, toM), [route, profile, fromM, toM]);
  const why = whyAvoid(facts);
  const [way, setWay] = useState<WayRound | "planning" | null>(null);
  const live = useRef(0);
  // A new stretch or route: the way round looked for goes, and an answer still coming is not shown.
  useEffect(() => {
    live.current += 1;
    setWay(null);
  }, [route, fromM, toM, preset, dials]);
  // The facts said once the region is in the page (a region that arrives filled is often not read), and again for
  // each new stretch.
  const line = factsLine(facts);
  const [said, setSaid] = useState("");
  useEffect(() => setSaid(line), [line]);
  // Try goes once pressed: the focus goes to the line that says what was found, not to the page.
  const wayRef = useRef<HTMLParagraphElement>(null);
  // The way round, drawn on the map while it is offered (Check a route's dashed green).
  useEffect(() => {
    const map = getMap();
    if (map) showCalmerWays(map, way !== null && way !== "planning" && way.kind === "found" ? [way.line] : []);
  }, [way, getMap]);
  useEffect(
    () => () => {
      const map = getMap();
      if (map) showCalmerWays(map, []);
    },
    [getMap],
  );

  const look = () => {
    const ask = (live.current += 1);
    setWay("planning");
    wayRef.current?.focus();
    void planAround(route, profile, facts, preset, dials, plan)
      .catch((): WayRound => ({ kind: "failed" }))
      .then((found) => {
        if (live.current === ask) setWay(found);
      });
  };

  const wayText = way === null ? "" : way === "planning" ? STRETCH_PLANNING : way.kind === "found" ? wayLine(way) : way.kind === "none" ? STRETCH_NO_WAY : STRETCH_FAILED;
  return (
    <div className="pc-stretch" role="group" aria-label={t("Picked stretch")}>
      <p className="pc-stretch-facts" aria-hidden="true">
        {line}
      </p>
      <p className="visually-hidden" role="status">
        {said}
      </p>
      <div className="pc-stretch-actions">
        {(why.busy || why.steep) && way === null && (
          <button type="button" className="secondary" onClick={look}>
            {STRETCH_AVOID}
          </button>
        )}
        {way !== null && way !== "planning" && way.kind === "found" && onUse && (
          <button type="button" className="secondary" onClick={() => onUse(asWorst(facts), way.line)}>
            {CHECK_USE}
          </button>
        )}
        <button type="button" className="link" onClick={onClear}>
          {STRETCH_CLEAR}
        </button>
      </div>
      <p className={way === "planning" ? "loading pc-stretch-way" : "hint pc-stretch-way"} role="status" tabIndex={-1} ref={wayRef}>
        {wayText}
      </p>
    </div>
  );
}
