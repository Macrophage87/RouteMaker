/**
 * A transit ride type's trip in the route panel (TRANSIT-ASSIST): the options, quickest first, as a
 * labelled list of buttons (riding the whole way is always one; the owner, 2026-10-12), then the
 * chosen one's scheduled total, the time of riding the whole way (said plainly when it is quicker),
 * the steps as a real ordered list named "Steps, in order" (ride, dock, walk, board, ride), the notes,
 * a legend that names each line on the map in words, and the source citations. Plain words, so a
 * screen reader hears the same plan the map draws, in the order it is ridden.
 */
import { useId } from "react";
import type { TransitPlan } from "./lib/api.ts";
import { WALK_CASING, WALK_COLOUR, WALK_DASH, WALK_LINE_WIDTH } from "./lib/bikeshare.ts";
import type { PresetId } from "./lib/presets.ts";
import { PresetName } from "./lib/presetName.ts";
import { OPTIONS_LABEL, STEPS_LABEL, TRACK_WORK, TRANSIT_COLOUR, TRANSIT_DASH, TRANSIT_LINE_WIDTH, optionSaid, optionText, stepIcon } from "./lib/transit.ts";
import { Icon } from "./Icon.tsx";
import { DepartureTimer } from "./DepartureTimer.tsx";

function Swatch({ colour, dash, width }: { colour: string; dash: [number, number]; width: number }) {
  return (
    <svg width="44" height="12" aria-hidden="true" focusable="false">
      <line x1="2" y1="6" x2="42" y2="6" stroke={WALK_CASING} strokeWidth={width + 3} strokeLinecap="round" />
      <line x1="2" y1="6" x2="42" y2="6" stroke={colour} strokeWidth={width} strokeLinecap="round" strokeDasharray={dash.map((d) => d * width).join(" ")} />
    </svg>
  );
}

export function TransitSummary({
  plan,
  preset,
  onPick,
  busy = false,
  announce,
  onMissed,
}: {
  plan: TransitPlan;
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
}) {
  const id = useId();
  return (
    <section className="transit" aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`}>
        <PresetName id={preset} suffix={`: ${plan.summary.replace(/\.$/, "")}`} />
      </h3>
      {plan.options.length > 1 && (
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
                <span aria-hidden="true">{optionText(option, index)}</span>
                <span className="visually-hidden">{optionSaid(option, index)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
      <p className="transit-total">
        <strong>{plan.summary}</strong>
      </p>
      {plan.departure && <DepartureTimer departure={plan.departure} announce={announce} onMissed={onMissed} />}
      {plan.comparison && <p className={plan.riding_quicker ? "transit-compare notice" : "transit-compare hint"}>{plan.comparison}</p>}
      {plan.live && plan.live.warnings.length > 0 && (
        // An elevator out where the bike needs one: a warning, never an avoidance (v0.7.0).
        <ul className="transit-warnings notice" aria-label="Warnings">
          {plan.live.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      <ol className="transit-steps" aria-label={STEPS_LABEL}>
        {plan.steps.map((step, index) => (
          <li key={index} className={`transit-step transit-${step.mode}`}>
            <Icon name={stepIcon(step)} size={16} />
            <span className="transit-step-text">{step.text}</span>
            {step.live && <span className="transit-step-live"> {step.live.text}</span>}
          </li>
        ))}
      </ol>
      {(plan.notes.length > 0 || (plan.live?.alerts.length ?? 0) > 0) && (
        <ul className="transit-notes" aria-label="Notes on this plan">
          {(plan.live?.alerts ?? []).map((alert) => (
            <li key={alert} className="hint transit-alert">
              {alert} ({plan.live?.credit}, live)
            </li>
          ))}
          {plan.notes.map((note) => (
            <li key={note} className="hint">
              {note}
            </li>
          ))}
        </ul>
      )}
      {plan.scheduled && (
        <>
          <p className="hint transit-legend">
            <Swatch colour={TRANSIT_COLOUR} dash={TRANSIT_DASH} width={TRANSIT_LINE_WIDTH} /> On the map, a dashed line marked with its
            system (Metro, MARC, Bus) is the ride on transit, through its stops.{" "}
            <Swatch colour={WALK_COLOUR} dash={WALK_DASH} width={WALK_LINE_WIDTH} /> A dotted line is a walk. The line coloured by traffic
            stress is the first ride, and a thin solid line is a ride after it.
          </p>
          <p className="hint transit-scheduled">
            {TRACK_WORK} Times are from each system's published timetables for this {plan.day_type === "weekday" ? "weekday" : plan.day_type}
            {plan.holiday ? " (a holiday)" : ""}: where trains or buses come every 15 minutes or less, the wait is half the time between
            them; otherwise it is the time to the next one. {plan.live ? "Times marked live are WMATA's next trains." : "Not live arrivals."}
          </p>
        </>
      )}
      {plan.credits.length > 0 && <p className="route-credit">Transit times: {plan.credits.join("; ")}.</p>}
      {plan.live && <p className="route-credit">Live: {plan.live.credit}.</p>}
    </section>
  );
}
