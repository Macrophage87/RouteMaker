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
import { BIKESHARE_HILLS, RIDE_SIZE_DEFAULT, WHENS, fitRideSize, offersBike, rideSizeOf, type Bike, type Dials, type When } from "./lib/dials.ts";
import { BIKES } from "./lib/bikeshare.ts";
import {
  MTB_LEVEL_LEGEND,
  MTB_LEVEL_OPTIONS,
  MTB_PREFERRED_LEGEND,
  isMtb,
  mtbLevelOf,
  mtbPreferredClamped,
  mtbPreferredOf,
  withMtbLevel,
  withMtbPreferred,
} from "./lib/mtbMode.ts";
import { RIDE_SIZE_LABEL, panelView, parseTarget, type SliderView } from "./lib/dialsPanel.ts";
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
        step={view.step ?? 5}
        value={view.scale ? view.scale.toSlider(props.value) : props.value}
        aria-labelledby={nameId}
        aria-valuetext={view.words}
        aria-describedby={view.note ? noteId : undefined}
        disabled={view.disabled}
        onChange={(event) => {
          const position = Number(event.target.value);
          props.onDraft(view.scale ? view.scale.fromSlider(position) : position);
        }}
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
function HowThisWorks({ text, about }: { text: string; about?: string }) {
  // `about`: a suffix read but not shown, so this one does not sound like the others in a list of
  // controls (the a11y review of wip/trails-off, N4).
  return (
    <details className="how">
      <summary>
        How this works{about && <span className="visually-hidden">: {about}</span>}
      </summary>
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

/** What When changes, in full, behind its How this works. */
const WHEN_HOW =
  "On weekends, roads closed to cars then, such as Beach Drive in Montgomery County and Sligo Creek Parkway, are planned as " +
  "traffic-free paths. With e-bike rules, on roads only, or on a mass ride, they count only as paths in the breakdown. Night " +
  "runs from 9 PM to 7 AM on every day, weekends included, and off-hours end at 9 PM. Crossing a busy road counts for more " +
  "at rush hour, and for less on weekends and at night, when traffic is usually calmer. Each junction warning says when the " +
  "time changed it.";

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

/** The dials with a ride size, the default taken off the object (so the link stays as it was). */
function withRideSize(dials: Dials, riders: number): Dials {
  const next: Dials = { ...dials };
  const fitted = fitRideSize(riders);
  if (fitted === undefined || fitted === RIDE_SIZE_DEFAULT) delete next.rideSize;
  else next.rideSize = fitted;
  return next;
}

/** The dials with the bike chosen: its hills start, and no ending outside a dock for a classic. */
function withBike(dials: Dials, bike: Bike): Dials {
  const next: Dials = { ...dials, bike, hills: BIKESHARE_HILLS[bike] };
  if (bike === "classic") delete next.ending;
  return next;
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
    if (now.stress !== was.stress || now.hills !== was.hills || now.rideSize !== was.rideSize) commit(now);
  };
  const release = (settle: boolean) => {
    if (settle) keys.current.later(commitDraft);
    else keys.current.now(commitDraft);
  };
  const view = panelView(preset, dials, draft);
  const trailsOffHintId = useId();
  // What lowering the hardest trail level did to the preferred one, said politely (never a silent clamp),
  // with the ride type and levels it was said of: a change from outside the panel (a link, a ride type, a
  // reset) clears it, so it never speaks of levels no longer shown.
  const mtbPreferredHintId = useId();
  const mtbKey = `${preset}:${mtbLevelOf(dials)}:${mtbPreferredOf(dials)}`;
  const [mtbClamp, setMtbClamp] = useState<{ said: string; key: string } | null>(null);
  useEffect(() => {
    if (mtbClamp && mtbClamp.key !== mtbKey) setMtbClamp(null);
  }, [mtbKey, mtbClamp]);
  const mtbClampSaid = mtbClamp?.key === mtbKey ? mtbClamp.said : "";
  return (
    <section className="dials" aria-labelledby="dials-heading">
      {/* Inside the Ride line's settings (Sidebar.tsx RideSettings), which is the h2. In the order of the
          sidebar redesign (OWNER-DECISIONS 312): Traffic and Hills, When, target distance, weight, keep to
          roads (OWNER-DECISIONS 463, 463b), avoid gravel; "Make it a loop" moved to the Points section (OWNER-DECISIONS 388). Every control and its behaviour is as before. */}
      {/* Shown on the Ride settings line that opens it (edit-route redesign); kept for a screen reader's heading list. */}
      <h3 id="dials-heading" className="visually-hidden">
        Ride settings
      </h3>
      {offersBike(preset) && (
        <fieldset className="bikeshare-bike">
          <legend>Bike</legend>
          {BIKES.map((option) => (
            <label key={option.id} className="toggle">
              <input
                type="radio"
                name="bikeshare-bike"
                value={option.id}
                checked={(dials.bike ?? "classic") === option.id}
                onChange={() => onCommit(withBike(dials, option.id))}
              />
              <span>
                {option.label}
                <span className="hint">{option.hint}</span>
              </span>
            </label>
          ))}
          <p className="hint">Choosing a bike moves the hills slider to where it starts for that bike.</p>
        </fieldset>
      )}
      {isMtb(preset) && (
        // Mountain Bike's hardest trail level (slice 6): four real radio buttons, each named by its level
        // number, colour name and words, never by colour alone.
        <fieldset className="mtb-level">
          <legend>{MTB_LEVEL_LEGEND}</legend>
          {MTB_LEVEL_OPTIONS.map((option) => (
            <label key={option.level} className="toggle">
              <input
                type="radio"
                name="mtb-level"
                value={option.level}
                checked={mtbLevelOf(dials) === option.level}
                onChange={() => {
                  const next = withMtbLevel(dials, option.level);
                  const said = mtbPreferredClamped(dials, next);
                  setMtbClamp(said ? { said, key: `${preset}:${mtbLevelOf(next)}:${mtbPreferredOf(next)}` } : null);
                  onCommit(next);
                }}
              />
              <span>
                {option.label}
                <span className="hint">{option.hint}</span>
              </span>
            </label>
          ))}
          <p className="hint">The route uses no trail harder than this where any other way exists, and says so where it must.</p>
        </fieldset>
      )}
      {isMtb(preset) && (
        // The preferred level (the second pass): the same four levels, those above the hardest level
        // disabled (the preferred level is never above it), and a polite status when a lower hardest
        // level lowered it.
        <fieldset className="mtb-level mtb-preferred" aria-describedby={mtbPreferredHintId}>
          <legend>{MTB_PREFERRED_LEGEND}</legend>
          {MTB_LEVEL_OPTIONS.map((option) => (
            <label key={option.level} className="toggle">
              <input
                type="radio"
                name="mtb-preferred"
                value={option.level}
                checked={mtbPreferredOf(dials) === option.level}
                disabled={option.level > mtbLevelOf(dials)}
                onChange={() => {
                  setMtbClamp(null);
                  onCommit(withMtbPreferred(dials, option.level));
                }}
              />
              <span>
                {option.label}
                {option.level > mtbLevelOf(dials) && <span className="visually-hidden"> (above your hardest level)</span>}
              </span>
            </label>
          ))}
          <p className="hint" id={mtbPreferredHintId}>
            Routes with trails at this level come first, then a level easier or harder; trails further from it count as
            any other trail. It can&apos;t be harder than your hardest level: raise that to prefer a harder one.
          </p>
          <p className="hint mtb-preferred-said" role="status">
            {mtbClampSaid}
          </p>
        </fieldset>
      )}
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
      {/* Mass Ride's "Anticipated ride size" (PLAN items 128, 129, 139): the corker load's group length. */}
      {view.rideSize && (
        <Slider
          label={RIDE_SIZE_LABEL}
          view={view.rideSize}
          value={rideSizeOf(draft)}
          onDraft={(riders) => setDraft(withRideSize(draft, riders))}
          onRelease={release}
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
        {/* One line, the rest behind How this works (Plan streamline, Stephen 2026-10-17). */}
        <p className="hint">Weekend car-free roads, such as Beach Drive and Sligo Creek Parkway, count as paths.</p>
        <HowThisWorks text={WHEN_HOW} about="when" />
      </fieldset>
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
      {/* The rider and bike weight is in Settings (the owner, 2026-10-18: "somewhere hidden, and probably belongs in settings"). */}
      <div className="dial trails-off">
        <label className="toggle">
          {/* aria-disabled, not disabled, when always on (Mass Ride): it stays in the Tab order with its
              reason in its description, and a press changes nothing (as the loop box does). */}
          <input
            type="checkbox"
            checked={view.trailsOff.checked}
            aria-disabled={view.trailsOff.locked || undefined}
            aria-describedby={trailsOffHintId}
            onChange={(event) => {
              if (view.trailsOff.locked) return;
              onCommit({ ...dials, trailsOff: event.target.checked });
            }}
          />
          {view.trailsOff.label}
        </label>
        <p className="hint" id={trailsOffHintId}>
          {view.trailsOff.hint}
        </p>
        <HowThisWorks text={view.trailsOff.how} about={view.trailsOff.howAbout} />
      </div>
      <label className="toggle">
        <input
          type="checkbox"
          checked={dials.avoidGravel === true}
          onChange={(event) => onCommit({ ...dials, avoidGravel: event.target.checked })}
        />
        Avoid gravel
      </label>
      {view.reset && (
        <button type="button" className="link" onClick={() => view.reset && onCommit(view.reset)}>
          Back to this ride type's settings
        </button>
      )}
    </section>
  );
}
