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
import { loopView } from "./lib/loop.ts";
import type { LonLat } from "./lib/geo.ts";
import { panelView, parseTarget, type SliderView } from "./lib/dialsPanel.ts";
import { defaultSplit, type StoredWeight } from "./lib/weight.ts";
import { WeightSetting } from "./lib/weightDialog.ts";
import { Debounce, KEY_SETTLE_MS } from "./lib/settle.ts";

interface Props {
  preset: PresetId;
  dials: Dials;
  onCommit: (dials: Dials) => void;
  /** The ride's points: a ride that ends where it starts is a loop (OWNER-DECISIONS 266). */
  points?: readonly LonLat[];
  /** What "Now" came to on the last route: one of the three settings. */
  resolvedWhen?: When | null;
  /** The rider and bike weight, kept by App (lib/weight.ts WeightStore): never in `dials` or the link. */
  weight?: {
    saved: StoredWeight | null;
    remembered: boolean;
    onSave: (weight: StoredWeight, remember: boolean) => void;
    onClear: () => void;
  };
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
      {view.how && <HowThisWorks text={view.how} />}
    </div>
  );
}

/** The detail a description would be too long for (the a11y review's N1): read when opened, not on every focus. */
function HowThisWorks({ text }: { text: string }) {
  return (
    <details className="how">
      <summary>How this works</summary>
      <p className="hint">{text}</p>
    </details>
  );
}

/**
 * An optional number the rider types, in US units (OWNER-DECISIONS 256, 264): it plans
 * when they leave the field or press Enter, never on each key, so a screen reader
 * hears one route. Empty is the default. An entry the planner will not take is said
 * in words under the field, and the field is marked invalid, not only coloured.
 *
 * The rule is said as well as shown (the a11y review's SF3): its paragraph is an
 * assertive live region that is always in the page, empty while the entry is fine,
 * so a screen reader speaks the rule when it is filled, whether the rider pressed
 * Enter (the focus stays in the field) or moved on with Tab. The same bad entry
 * twice is said twice (the trailing no-break space that alternates is not read).
 */
function NumberDial(props: {
  label: string;
  value: string;
  rule: string;
  hint: string;
  how?: string;
  parse: (text: string) => number | undefined | null;
  onCommit: (value: number | undefined) => void;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const ruleId = `${id}-rule`;
  const [text, setText] = useState(props.value);
  const [bad, setBad] = useState(0);
  useEffect(() => {
    setText(props.value);
    setBad(0);
  }, [props.value]);
  const commit = () => {
    const parsed = props.parse(text);
    if (parsed === null) {
      setBad((n) => n + 1);
      return;
    }
    setBad(0);
    if (props.parse(props.value) !== parsed) props.onCommit(parsed);
  };
  return (
    <div className="dial">
      <label htmlFor={id} className="dial-label">
        <span>{props.label}</span>
      </label>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={text}
        placeholder="Default"
        aria-describedby={bad ? `${hintId} ${ruleId}` : hintId}
        aria-invalid={bad > 0 || undefined}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
      />
      <p className="hint" id={hintId}>
        {props.hint}
      </p>
      <p className={bad ? "notice dial-rule" : "dial-rule"} id={ruleId} aria-live="assertive">
        {bad ? `${props.rule}${bad % 2 === 0 ? " " : ""}` : ""}
      </p>
      {props.how && <HowThisWorks text={props.how} />}
    </div>
  );
}

function whenLabel(when: When): string {
  return WHENS.find((option) => option.id === when)?.label ?? when;
}

/** The dials with one optional number set, or taken off the object where it is empty. */
function withField(dials: Dials, key: "targetDistanceM", value: number | undefined): Dials {
  const next: Dials = { ...dials };
  if (value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

/** The dials with the loop on, or off (taken off the object). */
function withLoop(dials: Dials, on: boolean): Dials {
  const next: Dials = { ...dials };
  if (on) next.loop = true;
  else delete next.loop;
  return next;
}

export function DialsPanel({ preset, dials, onCommit, resolvedWhen, points = [], weight }: Props) {
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
  const loop = loopView(preset, dials.loop, points);
  const loopHintId = useId();
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
      {loop && (
        <div className="dial">
          <label className="toggle">
            {/* aria-disabled, not disabled, when the ride is a loop already: it stays in
                the Tab order with its reason as its description (the a11y review's N6),
                and a press changes nothing. */}
            <input
              type="checkbox"
              checked={loop.checked}
              aria-disabled={loop.implied || undefined}
              aria-describedby={loopHintId}
              onChange={(event) => {
                if (loop.implied) return;
                onCommit(withLoop(dials, event.target.checked));
              }}
            />
            {loop.label}
          </label>
          <p className="hint" id={loopHintId}>
            {loop.hint}
          </p>
        </div>
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
      {view.target && (
        <NumberDial
          label={view.target.label}
          value={view.target.value}
          rule={view.target.rule}
          hint={view.target.hint}
          how={view.target.how}
          parse={parseTarget}
          onCommit={(targetDistanceM) => onCommit(withField(dials, "targetDistanceM", targetDistanceM))}
        />
      )}
      <Slider
        label="Hills"
        view={view.hills}
        value={draft.hills}
        onDraft={(hills) => setDraft({ ...draft, hills })}
        onRelease={release}
      />
      {/* The rider and bike weight: the line and Change, never the number (OWNER-DECISIONS 313-318). */}
      {view.weight && weight && (
        <WeightSetting
          saved={weight.saved}
          remembered={weight.remembered}
          split={defaultSplit(dials.carrying)}
          onSave={weight.onSave}
          onClear={weight.onClear}
        />
      )}
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
