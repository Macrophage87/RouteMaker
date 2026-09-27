/**
 * The ride type's sliders, the ride time and Cargo Bike's load, as one panel
 * section of its own (kept out of App.tsx, which another lane is changing).
 *
 * A slider moves freely while it is held and plans only when it is let go:
 * the pointer lifted, a key released, the focus gone. The scheduler folds
 * what arrives close together into one request (routeScheduler.ts), so a
 * rider pressing an arrow key ten times plans once, not ten times.
 */
import { useEffect, useId, useState } from "react";
import type { PresetId } from "./lib/presets.ts";
import {
  HILLS_MIN,
  STRESS_MAX,
  STRESS_MIN,
  WHENS,
  hillsMax,
  hillsWords,
  startDials,
  stressWords,
  type Dials,
  type When,
} from "./lib/dials.ts";

interface Props {
  preset: PresetId;
  dials: Dials;
  onCommit: (dials: Dials) => void;
}

function Slider(props: {
  label: string;
  min: number;
  max: number;
  value: number;
  ends: [string, string, string];
  words: string;
  disabledNote?: string;
  onDraft: (value: number) => void;
  onRelease: () => void;
}) {
  const id = useId();
  const [low, middle, high] = props.ends;
  return (
    <div className="dial">
      <label htmlFor={id} className="dial-label">
        {props.label}
        <span className="dial-now">{props.words}</span>
      </label>
      <input
        id={id}
        type="range"
        min={props.min}
        max={props.max}
        step={5}
        value={props.value}
        aria-valuetext={props.words}
        onChange={(event) => props.onDraft(Number(event.target.value))}
        onPointerUp={props.onRelease}
        onKeyUp={props.onRelease}
        onBlur={props.onRelease}
      />
      <div className="dial-ends" aria-hidden="true">
        <span>{low}</span>
        <span>{middle}</span>
        <span>{high}</span>
      </div>
      {props.disabledNote && <p className="hint">{props.disabledNote}</p>}
    </div>
  );
}

export function DialsPanel({ preset, dials, onCommit }: Props) {
  const [draft, setDraft] = useState(dials);
  useEffect(() => setDraft(dials), [dials]);
  const release = () => {
    if (draft.stress !== dials.stress || draft.hills !== dials.hills) onCommit(draft);
  };
  const seekAllowed = hillsMax(preset) > 0;
  const start = startDials(preset, dials.carrying, dials.when);
  const moved = dials.stress !== start.stress || dials.hills !== start.hills;
  return (
    <section className="dials" aria-labelledby="dials-heading">
      <h2 id="dials-heading">Adjust this ride</h2>
      <Slider
        label="Traffic"
        min={STRESS_MIN}
        max={STRESS_MAX}
        value={draft.stress}
        ends={["Direct roads", "Balanced", "Quiet roads"]}
        words={stressWords(draft.stress)}
        onDraft={(stress) => setDraft({ ...draft, stress })}
        onRelease={release}
      />
      <Slider
        label="Hills"
        min={HILLS_MIN}
        max={hillsMax(preset)}
        value={draft.hills}
        ends={seekAllowed ? ["Avoid hills", "Fastest", "Seek hills"] : ["Avoid hills", "", "Fastest"]}
        words={hillsWords(draft.hills)}
        disabledNote={
          seekAllowed
            ? draft.hills > 0
              ? "Looks for climbs among a few alternative routes, up to half again as long; for a start and an end only, up to 50 km apart."
              : undefined
            : "A mass ride does not look for climbs: at parade pace a climb drops riders below balance speed."
        }
        onDraft={(hills) => setDraft({ ...draft, hills })}
        onRelease={release}
      />
      <fieldset className="when">
        <legend>When</legend>
        <label className="toggle">
          <input
            type="radio"
            name="when"
            value=""
            checked={dials.when === null}
            onChange={() => onCommit({ ...dials, when: null })}
          />
          Now
        </label>
        {WHENS.map((option) => (
          <label key={option.id} className="toggle">
            <input
              type="radio"
              name="when"
              value={option.id}
              checked={dials.when === option.id}
              onChange={() => onCommit({ ...dials, when: option.id as When })}
            />
            {option.label}
          </label>
        ))}
        <p className="hint">
          Roads closed to cars at set times, such as Beach Drive at weekends, count as traffic-free paths in the
          breakdown when the ride is inside the closure.
        </p>
      </fieldset>
      {moved && (
        <button type="button" className="link" onClick={() => onCommit(start)}>
          Back to this ride type's settings
        </button>
      )}
    </section>
  );
}
