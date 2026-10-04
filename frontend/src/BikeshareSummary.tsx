/**
 * The bikeshare plan in the route panel (FOLLOWUP-BIKESHARE): the steps in plain words, the
 * totals, how fresh the availability is, an e-bike's choice of ending with the operator's fee
 * information, the notes, and the source citation. Plain words and a real list, so a screen
 * reader hears the same plan the map draws; the walk legs have a legend that names their
 * dotted line.
 */
import { useId } from "react";
import type { BikesharePlan } from "./lib/api.ts";
import type { Ending } from "./lib/dials.ts";
import {
  WALK_CASING,
  WALK_COLOUR,
  WALK_DASH,
  WALK_LINE_WIDTH,
  availabilityLine,
  bikeLabel,
  endingChoices,
  endingLabel,
  hasEndingChoice,
  totals,
} from "./lib/bikeshare.ts";

export function BikeshareSummary({
  plan,
  onEnding,
}: {
  plan: BikesharePlan;
  /** Plan this ending instead (an e-bike's choice). */
  onEnding: (ending: Ending) => void;
}) {
  const id = useId();
  const { offered, declined } = endingChoices(plan);
  const choice = hasEndingChoice(plan);
  const dash = WALK_DASH.map((d) => d * WALK_LINE_WIDTH).join(" ");
  return (
    <section className="bikeshare" aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`}>Bikeshare plan: {bikeLabel(plan.bike).toLowerCase()}</h3>
      <ol className="bikeshare-steps">
        {plan.steps.map((step, index) => (
          <li key={index} className={`bikeshare-step bikeshare-${step.kind}`}>
            {step.text}
          </li>
        ))}
      </ol>
      <dl className="stats bikeshare-totals">
        {totals(plan).map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="hint bikeshare-legend">
        <svg width="44" height="12" aria-hidden="true" focusable="false">
          <line x1="2" y1="6" x2="42" y2="6" stroke={WALK_CASING} strokeWidth={WALK_LINE_WIDTH + 3} strokeLinecap="round" />
          <line
            x1="2"
            y1="6"
            x2="42"
            y2="6"
            stroke={WALK_COLOUR}
            strokeWidth={WALK_LINE_WIDTH}
            strokeLinecap="round"
            strokeDasharray={dash}
          />
        </svg>{" "}
        On the map, a dotted line is a walk. A solid line is the ride between the docks, coloured by traffic stress,
        and the wheel markers numbered 1 and 2 are where you take and return the bike.
      </p>
      <p className="hint bikeshare-availability">{availabilityLine(plan)}</p>
      {choice ? (
        <fieldset className="bikeshare-endings">
          <legend>Where the ride ends</legend>
          {offered.map((ending) => (
            <label key={ending.kind} className="toggle">
              <input
                type="radio"
                name={`${id}-ending`}
                checked={ending.chosen}
                onChange={() => onEnding(ending.kind)}
              />
              <span>
                {endingLabel(ending.kind)}
                <span className="hint">{ending.text}</span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="hint bikeshare-ending">{offered[0]?.text}</p>
      )}
      {declined.map((ending) => (
        <p key={ending.kind} className="hint bikeshare-ending-declined">
          {ending.reason_text}
        </p>
      ))}
      {plan.pricing_note && <p className="hint bikeshare-pricing">{plan.pricing_note}</p>}
      {plan.notes.length > 0 && (
        <>
          <h4>Notes on this plan</h4>
          <ul className="bikeshare-notes">
            {plan.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </>
      )}
      <p className="route-credit bikeshare-credit">{plan.credit}.</p>
    </section>
  );
}
