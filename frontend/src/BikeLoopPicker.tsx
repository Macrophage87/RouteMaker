// A bike loop from a start and a distance (lib/bikeLoop.ts; backlog 2026-11-12 item 5, Plan only): with Make it a
// loop on and the start alone, one distance box and "Find loops"; then two or three shapes, each a radio with its
// miles, climb and share of quiet riding. Picking one plans it through its corners; the picker stays while the plan is
// one of its shapes, so another can be tried, and goes once the points are edited otherwise.
import { useEffect, useId, useRef, useState } from "react";
import type { Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import type { PresetId } from "./lib/presets.ts";
import { metricFirst } from "./lib/units.ts";
import { t } from "./lib/i18n.ts";
import { milesRange } from "./lib/format.ts";
import { cancelRoute } from "./lib/api.ts";
import { newPlanId } from "./lib/routeScheduler.ts";
import { parseTarget, targetText } from "./lib/dialsPanel.ts";
import {
  LOOP_MAX_M,
  LOOP_MIN_M,
  QUIET_MEANS,
  isShapeOf,
  keepLoopM,
  keptLoopM,
  offersBikeLoop,
  requestLoopShapes,
  shapeLine,
  shapeName,
  showsBikeLoop,
  type LoopShape,
} from "./lib/bikeLoop.ts";

interface Found {
  start: LonLat;
  preset: PresetId;
  shapes: LoopShape[];
}

export interface BikeLoopPickerProps {
  preset: PresetId;
  dials: Dials;
  points: readonly LonLat[];
  /** Plans the picked shape: App commits the points (lib/bikeLoop.ts shapePoints) as one edit. */
  onPick: (start: LonLat, shape: LoopShape) => void;
  announce: (text: string) => void;
}

const sameSpot = (a: LonLat, b: LonLat) => Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;

export function BikeLoopPicker({ preset, dials, points, onPick, announce }: BikeLoopPickerProps) {
  const id = useId();
  const [text, setText] = useState(() => targetText(keptLoopM()));
  const [found, setFound] = useState<Found | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // The search under way: what it was asked for, so one the rider has moved on from is stopped (and its server slot
  // given back) rather than planning a loop from the old start.
  const asking = useRef<{ controller: AbortController; planId: string; start: LonLat; preset: PresetId } | null>(null);
  const stop = () => {
    const running = asking.current;
    if (!running) return;
    asking.current = null;
    running.controller.abort();
    cancelRoute(running.planId);
    setBusy(false);
  };

  const askable = showsBikeLoop(preset, points, dials.loop === true);
  const picked = found && found.preset === preset ? found.shapes.findIndex((s) => isShapeOf(points, found.start, s)) : -1;
  // Shapes found for this start (one point, the same place), or the plan is one of them.
  const kept = found !== null && found.preset === preset && ((askable && sameSpot(points[0], found.start)) || picked >= 0);

  const running = asking.current;
  const stale = running !== null && (!askable || running.preset !== preset || !sameSpot(points[0], running.start));
  useEffect(() => {
    // The start moved, the ride type changed or the points were edited past a shape: the shapes go, and a search under
    // way for the old start or ride type is stopped.
    if (found && !kept) setFound(null);
    if (stale) stop();
    // `stop` reads refs only: the same work whichever render made it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [found, kept, stale]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => () => stop(), []);

  if (!offersBikeLoop(preset) || (!askable && !kept)) return null;

  const label = metricFirst() ? t("Distance (km)") : t("Distance (miles)");
  const find = async () => {
    const metres = parseTarget(text, LOOP_MAX_M);
    if (metres === undefined || metres === null || metres < LOOP_MIN_M) {
      setProblem(t("Enter {range}.", { range: milesRange(3, 100, LOOP_MIN_M, LOOP_MAX_M) }));
      return;
    }
    const start = points[0];
    keepLoopM(metres);
    setProblem(null);
    stop();
    setBusy(true);
    const controller = new AbortController();
    const planId = newPlanId();
    asking.current = { controller, planId, start, preset };
    announce(t("Finding loops."));
    const result = await requestLoopShapes(start, preset, dials, metres, { signal: controller.signal, planId });
    if (controller.signal.aborted || asking.current?.controller !== controller) return;
    asking.current = null;
    setBusy(false);
    if (!result.ok) {
      const said = result.error.message ? `${result.error.title}. ${result.error.message}` : result.error.title;
      setProblem(said);
      announce(said);
      return;
    }
    setFound({ start, preset, shapes: result.shapes });
    const n = result.shapes.length;
    announce(n === 1 ? t("One loop found; it is planned now.") : t("{n} loops found; the first is planned now.", { n }));
    // The best shape is planned at once; the others are one press away.
    onPick(start, result.shapes[0]);
  };

  return (
    <section className="bike-loop" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="bike-loop-title">
        {t("Loop by distance")}
      </h3>
      {askable && (
        <form
          className="bike-loop-ask"
          onSubmit={(event) => {
            event.preventDefault();
            void find();
          }}
        >
          <label htmlFor={`${id}-distance`}>{label}</label>
          <input
            id={`${id}-distance`}
            type="text"
            inputMode="decimal"
            value={text}
            size={5}
            aria-describedby={problem ? `${id}-problem` : undefined}
            aria-invalid={problem ? true : undefined}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="submit" disabled={busy} aria-busy={busy || undefined}>
            {busy ? t("Finding…") : t("Find loops")}
          </button>
        </form>
      )}
      {problem && (
        <p id={`${id}-problem`} className="hint warning" role="alert">
          {problem}
        </p>
      )}
      {found && kept && (
        <fieldset className="bike-loop-shapes">
          <legend>{t("Pick a shape")}</legend>
          {found.shapes.map((shape, i) => (
            <label key={`${shape.heading_deg}-${i}`} className="bike-loop-shape">
              <input
                type="radio"
                name={`${id}-shape`}
                checked={picked === i}
                onChange={() => onPick(found.start, shape)}
                aria-describedby={`${id}-line-${i}`}
              />
              <span className="bike-loop-name">{shapeName(shape)}</span>
              <span id={`${id}-line-${i}`} className="bike-loop-line">
                {shapeLine(shape)}
              </span>
            </label>
          ))}
          <p className="hint">{QUIET_MEANS}</p>
        </fieldset>
      )}
    </section>
  );
}
