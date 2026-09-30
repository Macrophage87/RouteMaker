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
import { WHENS, type Dials, type When } from "./lib/dials.ts";
import { panelView, type SliderView } from "./lib/dialsPanel.ts";

interface Props {
  preset: PresetId;
  dials: Dials;
  onCommit: (dials: Dials) => void;
  /** What "Now" came to on the last route: one of the three settings. */
  resolvedWhen?: When | null;
}

function Slider(props: {
  label: string;
  view: SliderView;
  value: number;
  onDraft: (value: number) => void;
  onRelease: () => void;
}) {
  const id = useId();
  const { view } = props;
  const [low, middle, high] = view.ends;
  return (
    <div className="dial">
      <label htmlFor={id} className="dial-label">
        {props.label}
        <span className="dial-now">{view.words}</span>
      </label>
      <input
        id={id}
        type="range"
        min={view.min}
        max={view.max}
        step={5}
        value={props.value}
        aria-valuetext={view.words}
        disabled={view.disabled}
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
      {view.note && <p className="hint">{view.note}</p>}
    </div>
  );
}

function whenLabel(when: When): string {
  return WHENS.find((option) => option.id === when)?.label ?? when;
}

export function DialsPanel({ preset, dials, onCommit, resolvedWhen }: Props) {
  const [draft, setDraft] = useState(dials);
  useEffect(() => setDraft(dials), [dials]);
  const release = () => {
    if (draft.stress !== dials.stress || draft.hills !== dials.hills) onCommit(draft);
  };
  const view = panelView(preset, dials, draft);
  return (
    <section className="dials" aria-labelledby="dials-heading">
      <h2 id="dials-heading">Adjust this ride</h2>
      {view.assistToggle && (
        <label className="toggle">
          <input
            type="checkbox"
            checked={dials.assist}
            onChange={(event) => onCommit({ ...dials, assist: event.target.checked })}
          />
          Electric assist
        </label>
      )}
      {view.assistNote && (
        <p className="hint">
          Follows e-bike rules and plans at a little more speed. Hills still count: a loaded cargo bike&apos;s motor
          rarely makes a climb easy. With a strong motor, move the hills slider toward Fastest yourself.
        </p>
      )}
      <label className="toggle">
        <input
          type="checkbox"
          checked={dials.avoidGravel === true}
          onChange={(event) => onCommit({ ...dials, avoidGravel: event.target.checked })}
        />
        Avoid gravel
      </label>
      <Slider
        label="Traffic"
        view={view.traffic}
        value={draft.stress}
        onDraft={(stress) => setDraft({ ...draft, stress })}
        onRelease={release}
      />
      {view.warning && (
        <p className="notice traffic-tolerant" role="note">
          {view.warning}
        </p>
      )}
      <Slider
        label="Hills"
        view={view.hills}
        value={draft.hills}
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
          {dials.when === null && resolvedWhen ? ` (${whenLabel(resolvedWhen)})` : ""}
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
          On weekends, roads closed to cars then, such as Beach Drive in Montgomery County and Sligo Creek Parkway,
          are planned as traffic-free paths. With e-bike rules or on a mass ride they are only counted as paths in
          the breakdown.
        </p>
      </fieldset>
      {view.reset && (
        <button type="button" className="link" onClick={() => view.reset && onCommit(view.reset)}>
          Back to this ride type's settings
        </button>
      )}
    </section>
  );
}
