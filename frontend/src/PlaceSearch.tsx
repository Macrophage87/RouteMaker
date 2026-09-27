/**
 * The search box: type a place, pick it, and it becomes the start, the
 * destination or a via (lib/geocode.ts, applyPlace).
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
  fetchPlaces,
  normalQuery,
  placeRole,
  placesFor,
  searchUrl,
  type GeoGate,
  type GeoResult,
  type Place,
  type PlaceRole,
} from "./lib/geocode.ts";
import type { LonLat } from "./lib/geo.ts";

// App.tsx's phone layout, where the panel is a bottom sheet.
const PHONE = "(max-width: 720px)";

const ROLE_HINT: Record<PlaceRole, string> = {
  start: "The place you pick becomes the start.",
  end: "The place you pick becomes the destination.",
  "replace-end": "The place you pick becomes the new destination.",
  via: "The place you pick is added as a stop along the way.",
};

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
}: {
  pointCount: number;
  /** The plan has as many points as a route can take. */
  full: boolean;
  gate: GeoGate;
  /** Where results should lean towards: the map's centre, when it is in the area. */
  bias: () => LonLat | undefined;
  onPick: (place: Place, asVia: boolean) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<GeoResult | null>(null);
  const [answered, setAnswered] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [asVia, setAsVia] = useState(false);
  const runner = useRef<PlaceSearchRunner | null>(null);
  const biasRef = useRef(bias);
  biasRef.current = bias;
  if (runner.current === null) {
    runner.current = new PlaceSearchRunner({
      send: (q) => gate.run(() => fetchPlaces(searchUrl(q, biasRef.current())), true),
      onResult: (q, r) => {
        setResult(r);
        setAnswered(q);
        setActive(-1);
        setOpen(true);
      },
    });
  }
  useEffect(() => () => runner.current?.clear(), []);

  const role = placeRole(pointCount, asVia && pointCount >= 2);
  const current = normalQuery(query);
  const places = placesFor(query, answered, result);
  const answeredNow = result !== null && current === answered;
  const searching = current.length >= MIN_QUERY_CHARS && !answeredNow;
  const expanded = open && places.length > 0;
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
    onPick(place, asVia && pointCount >= 2);
    setQuery("");
    setResult(null);
    setOpen(false);
    setActive(-1);
    runner.current?.clear();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (places.length === 0) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a + step + places.length) % places.length);
    } else if (event.key === "Enter") {
      if (!expanded) return;
      event.preventDefault();
      pick(places[active >= 0 ? active : 0]);
    } else if (event.key === "Escape") {
      if (expanded) {
        event.preventDefault();
        setOpen(false);
        setActive(-1);
      } else if (query) {
        event.preventDefault();
        change("");
      }
    }
  };

  return (
    <div className="place-search">
      <label htmlFor={`${id}-input`} className="place-search-label">
        Find a place
      </label>
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
        disabled={full}
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
      <ul id={listId} role="listbox" aria-label="Places found" className="place-results" hidden={!expanded}>
        {places.map((place, i) => (
          <li
            key={`${place.lon},${place.lat},${place.label}`}
            id={optionId(i)}
            role="option"
            aria-selected={i === active}
            className={i === active ? "active" : undefined}
            // Before the input's blur, which would close the list first.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => pick(place)}
          >
            <span className="place-name">{place.name}</span>
            {place.label !== place.name && <span className="place-label">{place.label}</span>}
          </li>
        ))}
      </ul>
      {expanded && result?.ok && result.attribution.length > 0 && (
        <p className="place-credit">Search: {result.attribution.join("; ")}</p>
      )}
      <p id={`${id}-hint`} className="hint">
        {full ? "The route has as many points as it can take." : ROLE_HINT[role]}
      </p>
      {pointCount >= 2 && !full && (
        <label className="toggle">
          <input type="checkbox" checked={asVia} onChange={(event) => setAsVia(event.target.checked)} />
          Add as a stop along the way instead
        </label>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {answeredNow ? searchStatus(result, answered) : ""}
      </p>
      {searching && <p className="hint">Searching…</p>}
      {answeredNow && result && (!result.ok || result.places.length === 0) && (
        <p className="hint">{searchStatus(result, answered)}</p>
      )}
    </div>
  );
}
