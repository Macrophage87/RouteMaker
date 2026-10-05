/**
 * The search box: type a place, pick it, and it becomes the start, the
 * destination or a stop, as chosen (lib/geocode.ts, applyPlace). Each result
 * shows a short type from its OSM tag, and the list says it holds only places
 * in this map's area.
 *
 * The ARIA 1.2 combobox pattern: the input owns a listbox, the arrow keys
 * move through the options without leaving the input (aria-activedescendant),
 * Enter picks, Escape closes and then clears. The result count is announced
 * in a polite live region, and the options are tall enough to tap.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  MAX_QUERY_CHARS,
  MIN_QUERY_CHARS,
  PlaceSearchRunner,
  comboboxKey,
  pickTarget,
  placeEffectHint,
  placeType,
  searchSender,
  searchView,
  type GeoGate,
  type GeoResult,
  type Place,
  type PlaceChoice,
} from "./lib/geocode.ts";
import type { LonLat } from "./lib/geo.ts";
import { FINDING_LOCATION, hereEffectLine, locationMatches, searchStatusWithHere } from "./lib/geolocation.ts";

// App.tsx's phone layout, where the panel is a bottom sheet.
const PHONE = "(max-width: 720px)";

/** "Use my location" (OWNER-DECISIONS 395): the button beside the search and the "Your location" choice. */
export interface LocateControl {
  support: { available: true } | { available: false; reason: string };
  /** A look-up is under way. */
  busy: boolean;
  /** What the app adds under the button once a point is the rider's location (approximate). */
  note: string;
  /**
   * A look-up: from the button with no choice (it goes in like a map click), or
   * from the "Your location" choice in the list with the Start / Destination /
   * Stop choice in force (it goes in like a picked place).
   */
  onLocate: (choice?: PlaceChoice) => void;
}

/** The "Your location" choice in the list, ahead of the places found. */
const HERE = "here" as const;

const CHOICE_LABEL: Record<PlaceChoice, string> = { start: "Start", end: "Destination", via: "Stop" };

export function searchStatus(result: GeoResult | null, query: string): string {
  if (result === null) return "";
  if (!result.ok) {
    return result.status === 429 || result.status === 503
      ? "Search is busy; keep typing or try again in a moment."
      : "Place search is not available right now.";
  }
  if (result.places.length === 0) return `No places found for “${query}” in this map's area.`;
  return result.places.length === 1 ? "1 place found." : `${result.places.length} places found.`;
}

export function PlaceSearch({
  pointCount,
  full,
  gate,
  bias,
  onPick,
  loop = false,
  locate,
}: {
  /** Absent: no "Use my location" (a test or a build without it). */
  locate?: LocateControl;
  /** "Make it a loop" is on: a place is the start or a stop, never a destination (OWNER-DECISIONS 374). */
  loop?: boolean;
  pointCount: number;
  /** The plan has as many points as a route can take. */
  full: boolean;
  gate: GeoGate;
  /** Where results should lean towards: the map's centre, when it is in the area. */
  bias: () => LonLat | undefined;
  onPick: (place: Place, choice: PlaceChoice) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<GeoResult | null>(null);
  const [answered, setAnswered] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  // What the rider asked a pick to be; null until they choose, which follows
  // the plan (the start of an empty plan, then the destination).
  const [chosen, setChosen] = useState<PlaceChoice | null>(null);
  const runner = useRef<PlaceSearchRunner | null>(null);
  const biasRef = useRef(bias);
  biasRef.current = bias;
  if (runner.current === null) {
    runner.current = new PlaceSearchRunner({
      send: searchSender(gate, () => biasRef.current()),
      onResult: (q, r) => {
        setResult(r);
        setAnswered(q);
        setActive(-1);
        setOpen(true);
      },
    });
  }
  useEffect(() => () => runner.current?.clear(), []);

  const { places, answeredNow, searching, choices, choice, effect } = searchView({
    query,
    answered,
    result,
    open,
    pointCount,
    full,
    chosen,
    loop,
  });
  // "Your location" leads the list while the box is empty or says so; it is never the Enter default.
  const showHere = locate?.support.available === true && locationMatches(query);
  const items: (Place | typeof HERE)[] = showHere ? [HERE, ...places] : places;
  const expanded = open && items.length > 0;
  const listId = `${id}-list`;
  const optionId = (i: number) => `${id}-opt-${i}`;

  const change = (value: string) => {
    setQuery(value);
    setOpen(true);
    if (value.trim().length < MIN_QUERY_CHARS) {
      runner.current?.clear();
      setResult(null);
    } else {
      runner.current?.request(value);
    }
  };

  const pick = (place: Place) => {
    onPick(place, choice);
    setQuery("");
    setResult(null);
    setOpen(false);
    setActive(-1);
    runner.current?.clear();
  };

  const pickHere = () => {
    setQuery("");
    setResult(null);
    setOpen(false);
    setActive(-1);
    runner.current?.clear();
    locate?.onLocate(choice);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const action = comboboxKey(event.key, {
      active,
      count: items.length,
      expanded,
      hasQuery: query !== "",
    });
    if (action.kind === "none") return;
    event.preventDefault();
    if (action.kind === "move") {
      setOpen(true);
      setActive(action.active);
    } else if (action.kind === "pick") {
      // Enter with nothing highlighted takes the first place, never "Your location" (a look-up asks the browser's permission).
      const item = pickTarget(active, action.index, items, places);
      if (item === HERE) pickHere();
      else if (item) pick(item);
    } else if (action.kind === "close") {
      setOpen(false);
      setActive(-1);
    } else {
      change("");
    }
  };

  return (
    <div className="place-search">
      <label htmlFor={`${id}-input`} className="place-search-label">
        Find a place
      </label>
      <div className={locate ? "place-search-row" : undefined}>
      <input
        id={`${id}-input`}
        type="search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded && active >= 0 ? optionId(active) : undefined}
        aria-describedby={`${id}-hint`}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="search"
        maxLength={MAX_QUERY_CHARS}
        placeholder="A place, an address or a street"
        value={query}
        onChange={(event) => change(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
        onFocus={(event) => {
          setOpen(true);
          // On a phone the sheet is half the screen and the keyboard takes
          // much of the rest: bring the box to the top of the sheet so the
          // results under it can be seen.
          if (window.matchMedia(PHONE).matches) event.currentTarget.scrollIntoView({ block: "start" });
        }}
      />
      {locate && (
        <button
          type="button"
          className="secondary locate-button"
          // aria-disabled, not disabled: it stays in the Tab order with its reason as its description,
          // and a press changes nothing while it cannot work. While a look-up is under way a press starts
          // no second one; the app says "Finding your location…" again, so the press gets an answer.
          aria-disabled={!locate.support.available || locate.busy || undefined}
          aria-describedby={!locate.support.available ? `${id}-locate-why` : locate.busy ? `${id}-locate-busy` : undefined}
          onClick={() => {
            if (locate.support.available) locate.onLocate();
          }}
        >
          Use my location
        </button>
      )}
      </div>
      {locate && !locate.support.available && (
        <p id={`${id}-locate-why`} className="hint">
          {locate.support.reason}
        </p>
      )}
      {locate && locate.busy && (
        <p id={`${id}-locate-busy`} className="hint">
          {FINDING_LOCATION}
        </p>
      )}
      {locate && !locate.busy && locate.note && <p className="hint">{locate.note}</p>}
      <ul id={listId} role="listbox" aria-label="Places found" className="place-results" hidden={!expanded}>
        {items.map((item, i) =>
          item === HERE ? (
            <li
              key="your-location"
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(event) => event.preventDefault()}
              onClick={pickHere}
            >
              <span className="place-name">Your location</span>
              <span className="place-label">{hereEffectLine(effect, loop)}</span>
            </li>
          ) : (
            <li
              key={`${item.lon},${item.lat},${item.label}`}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              // Before the input's blur, which would close the list first.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(item)}
            >
              <span className="place-name">
                {item.name} <span className="place-type">{placeType(item)}</span>
              </span>
              {item.label !== item.name && <span className="place-label">{item.label}</span>}
            </li>
          ),
        )}
      </ul>
      {expanded && places.length > 0 && (
        <p className="place-credit">
          Only places in this map's area.
          {result?.ok && result.attribution.length > 0 && <> Search: {result.attribution.join("; ")}</>}
        </p>
      )}
      {choices.length > 1 && (
        <fieldset className="place-choice">
          <legend>Use the place as</legend>
          {choices.map((option) => (
            <label key={option}>
              <input
                type="radio"
                name={`${id}-choice`}
                value={option}
                checked={choice === option}
                onChange={() => setChosen(option)}
              />
              {CHOICE_LABEL[option]}
            </label>
          ))}
        </fieldset>
      )}
      <p id={`${id}-hint`} className="hint">
        {placeEffectHint(effect, loop)}
        {full && " The route has as many points as it can take, so no stop can be added."}
      </p>
      <p className="visually-hidden" role="status" aria-live="polite">
        {answeredNow ? searchStatusWithHere(searchStatus(result, answered), expanded && showHere) : ""}
      </p>
      {searching && <p className="hint">Searching…</p>}
      {answeredNow && result && (!result.ok || result.places.length === 0) && (
        <p className="hint">{searchStatus(result, answered)}</p>
      )}
    </div>
  );
}
