/**
 * A transit ride type's trip in the route panel (TRANSIT-ASSIST): the options, quickest first, as a
 * labelled list of buttons (riding the whole way is always one; the owner, 2026-10-12), then the
 * chosen one's scheduled total, the time of riding the whole way (said plainly when it is quicker),
 * the steps as a real ordered list named "Steps, in order" (ride, dock, walk, board, ride), the notes,
 * a legend that names each line on the map in words, and the source citations. Plain words, so a
 * screen reader hears the same plan the map draws, in the order it is ridden.
 */
import { useId } from "react";
import type { StressSpan, TransitPlan, TransitStep } from "./lib/api.ts";
import { WALK_CASING, WALK_COLOUR, WALK_DASH, WALK_LINE_WIDTH } from "./lib/bikeshare.ts";
import type { PresetId } from "./lib/presets.ts";
import { PresetName } from "./lib/presetName.ts";
import {
  OPTIONS_LABEL,
  RIDES_LEGEND,
  STEPS_LABEL,
  TRACK_WORK,
  TRANSIT_COLOUR,
  TRANSIT_DASH,
  TRANSIT_LINE_WIDTH,
  liveTimesText,
  optionSaid,
  optionText,
  stepIcon,
  stepStressSaid,
  timesFromText,
  tripNotes,
} from "./lib/transit.ts";
import { legsSaid, legsText } from "./lib/transitMarks.ts";
import { Icon } from "./Icon.tsx";
import { DepartureTimer } from "./DepartureTimer.tsx";
import { RIDE_REST, RIDE_REST_HINT } from "./lib/rideTrip.ts";
import { t } from "./lib/i18n.ts";
import { walkTurnTexts } from "./lib/walkCues.ts";

function Swatch({ colour, dash, width }: { colour: string; dash: [number, number]; width: number }) {
  return (
    <svg width="44" height="12" aria-hidden="true" focusable="false">
      <line x1="2" y1="6" x2="42" y2="6" stroke={WALK_CASING} strokeWidth={width + 3} strokeLinecap="round" />
      <line x1="2" y1="6" x2="42" y2="6" stroke={colour} strokeWidth={width} strokeLinecap="round" strokeDasharray={dash.map((d) => d * width).join(" ")} />
    </svg>
  );
}

/**
 * A step's detail, closed until asked for (Stephen, 2026-11-02; the inverted pyramid): a transit step's stops after the
 * one boarded, the last one the stop to get off; a walk's turns, in the words Ride says them.
 */
function StepMore({ step }: { step: TransitStep }) {
  const stops = (step.stops ?? []).slice(1);
  const turns = walkTurnTexts(step.turns);
  if (stops.length > 0) {
    return (
      <details className="transit-step-more">
        <summary>{stops.length === 1 ? t("1 transit stop") : t("{count} transit stops", { count: stops.length })}</summary>
        <ol>
          {stops.map((stop, i) => (
            <li key={`${i}-${stop.name}`}>
              {/* Marked in words too, as stop by stop's card is: a screen reader does not say bold (the release review's N2). */}
              {i === stops.length - 1 ? (
                <>
                  <strong>{stop.name}</strong> · {t("get off")}
                </>
              ) : (
                stop.name
              )}
            </li>
          ))}
        </ol>
      </details>
    );
  }
  if (turns.length > 0) {
    return (
      <details className="transit-step-more">
        <summary>{turns.length === 1 ? t("1 turn") : t("{count} turns", { count: turns.length })}</summary>
        <ol>
          {turns.map((turn, i) => (
            <li key={`${i}-${turn}`}>{turn}</li>
          ))}
        </ol>
      </details>
    );
  }
  return null;
}

export function TransitSummary({
  plan,
  preset,
  onPick,
  busy = false,
  announce,
  onMissed,
  lineSpans,
  onRideRest,
  go = false,
}: {
  plan: TransitPlan;
  /** The route's own stress sections: its line is the first ride's, said in that step's words. */
  lineSpans?: readonly StressSpan[];
  /** The ride type, for the heading: its name (emoji kept from a screen reader) and the total. */
  preset: PresetId;
  /** Plan another option, by its key; absent, the options are listed but not pressable. */
  onPick?: (key: string) => void;
  /** A plan is on its way: the buttons wait. */
  busy?: boolean;
  /** The page's status line, for the departure's milestones and a miss. */
  announce?: (text: string) => void;
  /** The departure would be missed: plan again, for the next one. */
  onMissed?: () => void;
  /** Ride the rest (lib/rideTrip.ts), where the trip has a riding leg after its transit. */
  onRideRest?: () => void;
  /**
   * Go's sheet (Stephen 2026-11-12, "Fold the steps shut in Go"): the trip on one screen, its legs as one strip and
   * the next departure; the steps, notes and map legend behind "Steps, in order", the other trips behind their own
   * fold, and no second total (Go's sheet shows the time and arrival above). Plan keeps everything open.
   */
  go?: boolean;
}) {
  const id = useId();
  // The trip's own lines' notes, each said once (P11; lib/transit.ts tripNotes).
  const notes = tripNotes(plan);
  const chosen = plan.options.find((option) => option.chosen);
  const options = plan.options.length > 1 && (
    <ol className="transit-options" aria-label={OPTIONS_LABEL}>
      {plan.options.map((option, index) => (
        <li key={option.key}>
          <button
            type="button"
            className={option.chosen ? "transit-option chosen" : "transit-option"}
            aria-pressed={option.chosen}
            aria-disabled={busy || !onPick || undefined}
            onClick={() => {
              if (!busy && onPick && !option.chosen) onPick(option.key);
            }}
          >
            <span aria-hidden="true">
              {optionText(option, index)}
              {option.elevator_out && <Icon name="elevator-out" size={16} />}
            </span>
            <span className="visually-hidden">{optionSaid(option, index)}</span>
          </button>
        </li>
      ))}
    </ol>
  );
  const steps = (
    <ol className="transit-steps" aria-label={STEPS_LABEL}>
      {plan.steps.map((step, index) => {
        // Each ride's traffic stress, in the route chart's words (every ride's, the first's too).
        const stress = stepStressSaid(step, lineSpans);
        return (
          <li key={index} className={`transit-step transit-${step.mode}`}>
            <Icon name={stepIcon(step)} size={16} />
            <span className="transit-step-text">{step.text}</span>
            {stress && <span className="transit-step-stress"> {stress}</span>}
            {step.live && <span className="transit-step-live"> {step.live.text}</span>}
            <StepMore step={step} />
          </li>
        );
      })}
    </ol>
  );
  const rideRest = onRideRest && (
    <div className="actions transit-rest">
      <button type="button" className="secondary" onClick={onRideRest} aria-describedby={`${id}-rest`}>
        {RIDE_REST}
      </button>
      <p id={`${id}-rest`} className="hint">
        {RIDE_REST_HINT}
      </p>
    </div>
  );
  const noteList = (notes.length > 0 || (plan.live?.alerts.length ?? 0) > 0) && (
    <ul className="transit-notes" aria-label={t("Notes on this plan")}>
      {(plan.live?.alerts ?? []).map((alert) => (
        <li key={alert} className="hint transit-alert">
          {alert} {t("({credit}, live)", { credit: plan.live?.credit ?? "" })}
        </li>
      ))}
      {notes.map((note) => (
        <li key={note} className="hint">
          {note}
        </li>
      ))}
    </ul>
  );
  const legend = plan.scheduled && (
    <>
      <p className="hint transit-legend">
        <Swatch colour={TRANSIT_COLOUR} dash={TRANSIT_DASH} width={TRANSIT_LINE_WIDTH} />{" "}
        {t("On the map, a dashed line marked with its system (Metro, MARC, Bus) is the ride on transit, through its stops.")}{" "}
        <Swatch colour={WALK_COLOUR} dash={WALK_DASH} width={WALK_LINE_WIDTH} /> {t("A dotted line is a walk.")} {RIDES_LEGEND}
      </p>
      <p className="hint transit-scheduled">
        {TRACK_WORK} {timesFromText(plan)} {liveTimesText(plan)}
      </p>
    </>
  );
  const head = (
    <h3 id={`${id}-heading`} className={go ? "visually-hidden" : undefined}>
      <PresetName id={preset} suffix={`: ${plan.summary.replace(/\.$/, "")}`} />
    </h3>
  );
  const elevatorWarnings = plan.live && plan.live.warnings.length > 0 && (
    // An elevator out where the bike needs one: a warning, never an avoidance (v0.7.0).
    <ul className="transit-warnings notice" aria-label={t("Warnings")}>
      {plan.live.warnings.map((warning) => (
        <li key={warning}>{warning}</li>
      ))}
    </ul>
  );
  const comparison = plan.comparison && <p className={plan.riding_quicker ? "transit-compare" : "transit-compare hint"}>{plan.comparison}</p>;
  if (go) {
    return (
      <section className="transit transit-go" aria-labelledby={`${id}-heading`}>
        {head}
        {/* The chosen trip's legs as one strip ("🚲 6 min · 🔴 18 min · 🚲 4 min"), said in words. */}
        {chosen?.legs && chosen.legs.length > 0 && (
          <p className="transit-legs">
            <span aria-hidden="true">{legsText(chosen.legs)}</span>
            <span className="visually-hidden">{legsSaid(chosen.legs)}</span>
          </p>
        )}
        {plan.departure && <DepartureTimer departure={plan.departure} announce={announce} onMissed={onMissed} />}
        {elevatorWarnings}
        {comparison}
        <details className="transit-steps-fold">
          <summary>{STEPS_LABEL}</summary>
          {steps}
          {noteList}
          {legend}
        </details>
        {options && (
          <details className="transit-options-fold">
            <summary>{OPTIONS_LABEL}</summary>
            {options}
          </details>
        )}
        {rideRest}
      </section>
    );
  }
  return (
    <section className="transit" aria-labelledby={`${id}-heading`}>
      {head}
      {options}
      <p className="transit-total">
        <strong>{plan.summary}</strong>
      </p>
      {plan.departure && <DepartureTimer departure={plan.departure} announce={announce} onMissed={onMissed} />}
      {/* Riding the whole way quicker is a plain line, not a warning box (P11): nothing is wrong. */}
      {comparison}
      {elevatorWarnings}
      {steps}
      {rideRest}
      {noteList}
      {legend}
      {/* The trip's sources (its schedules and WMATA's live data) are in the route's Info, once (P10). */}
    </section>
  );
}
