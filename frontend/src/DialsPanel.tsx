/**
 * The ride type's sliders, the ride time and Cargo Bike's load, as one panel
 * section of its own (kept out of App.tsx, which another lane is changing).
 *
 * A slider moves freely while it is held and plans only when it is let go:
 * the pointer lifted, a key released, the focus gone. The scheduler folds
 * what arrives close together into one request (routeScheduler.ts), so a
 * rider pressing an arrow key ten times plans once, not ten times; the keys
 * also wait for a short rest before they count as let go (lib/settle.ts), so
 * a screen reader hears one route, not one for each step.
 *
 * A slider's name is its label alone, and its words are its value (its
 * aria-valuetext): read once each, not "Traffic Calmest: ..." and then the
 * same words again (a11y review of integrate-2). The note under it is its
 * description.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { PresetId } from "./lib/presets.ts";
import { WHENS, type Dials, type When } from "./lib/dials.ts";
import { panelView, type SliderView } from "./lib/dialsPanel.ts";
import { Debounce, KEY_SETTLE_MS } from "./lib/settle.ts";

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
  /** Let go: `settle` for a key, which waits for the keys to rest. */
  onRelease: (settle: boolean) => void;
}) {
  const id = useId();
  const nameId = `${id}-name`;
  const noteId = `${id}-note`;
  const { view } = props;
  const [low, middle, high] = view.ends;
  return (
    <div className="dial">
      <label htmlFor={id} className="dial-label">
        <span id={nameId}>{props.label}</span>
        <span className="dial-now" aria-hidden="true">
          {view.words}
        </span>
      </label>
      <input
        id={id}
        type="range"
        min={view.min}
        max={view.max}
        step={5}
        value={props.value}
        aria-labelledby={nameId}
        aria-valuetext={view.words}
        aria-describedby={view.note ? noteId : undefined}
        disabled={view.disabled}
        onChange={(event) => props.onDraft(Number(event.target.value))}
        onPointerUp={() => props.onRelease(false)}
        onKeyUp={() => props.onRelease(true)}
        onBlur={() => props.onRelease(false)}
      />
      <div className="dial-ends" aria-hidden="true">
        <span>{low}</span>
        <span>{middle}</span>
        <span>{high}</span>
      </div>
      {view.note && (
        <p className="hint" id={noteId}>
          {view.note}
        </p>
      )}
    </div>
  );
}

function whenLabel(when: When): string {
  return WHENS.find((option) => option.id === when)?.label ?? when;
}

export function DialsPanel({ preset, dials, onCommit, resolvedWhen }: Props) {
  const [draft, setDraft] = useState(dials);
  useEffect(() => setDraft(dials), [dials]);
  // The latest of each, for a release that runs after the keys rest.
  const latest = useRef({ draft, dials, onCommit });
  latest.current = { draft, dials, onCommit };
  const keys = useRef(new Debounce(KEY_SETTLE_MS));
  useEffect(() => () => keys.current.cancel(), []);
  const commitDraft = () => {
    const { draft: now, dials: was, onCommit: commit } = latest.current;
    if (now.stress !== was.stress || now.hills !== was.hills) commit(now);
  };
  const release = (settle: boolean) => {
    if (settle) keys.current.later(commitDraft);
    else keys.current.now(commitDraft);
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
