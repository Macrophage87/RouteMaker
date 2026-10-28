/**
 * The search box: type a place, pick it, and it becomes the start, the
 * destination or a stop, as chosen (lib/geocode.ts, applyPlace). Each result
 * shows a short type from its OSM tag, and the list says it holds only places
 * in this map's area.
 *
 * The ARIA 1.2 combobox pattern: the input owns a listbox, the arrow keys
 * move through the options without leaving the input (aria-activedescendant),
 * Enter picks, Escape closes and then clears. The empty box lists "Your
 * location" and then the last places picked (lib/recentPlaces.ts). The result count is announced
 * in a polite live region, and the options are tall enough to tap.
 *
 * A pasted map link (Google, Apple, Waze, geo:) or typed coordinates are read as a place
 * (lib/sharedLocation.ts, v0.7.0 "Open shared locations"): it leads the list as one option, and a short
 * link is followed by the server first.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
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
import { Icon } from "./Icon.tsx";
import { readRecentPlaces, rememberRecentPlace } from "./lib/recentPlaces.ts";
import { FINDING_LOCATION, hereEffectLine, locationMatches, searchStatusWithHere } from "./lib/geolocation.ts";
import { parseShared, readShared, sharedPlace, SHARED_OPENING } from "./lib/sharedLocation.ts";
import { watchKeyboard } from "./lib/keyboardLift.ts";
import { t } from "./lib/i18n.ts";

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
  /** "Your location" in the list only, no button (Plan's Add a stop: the button sits on From and To). */
  listOnly?: boolean;
}

/** What a Go or Home search does with the place picked (UI-CLEANUP). */
const SINGLE_HINT = {
  go: t("The place you pick is where the route goes, from the start above."),
  home: t("The place you pick is kept as your Home."),
  work: t("The place you pick is kept as your Work, in Favorites."),
  favorite: t("The place you pick is saved to Favorites."),
  start: t("The place you pick is where the route starts, in place of your location."),
  stop: t("The place you pick is a stop, where it adds the least distance."),
  from: t("The place you pick becomes the start."),
  to: t("The place you pick becomes the destination."),
  add: t("The place you pick is added as a stop, where it adds the least distance."),
} as const;

/**
 * Plan's own boxes (Plan streamline, Stephen 2026-10-17): From, To and Add a stop, each with one job, in place of
 * one "Find a place" box and its Start / Destination / Stop choice. What each box's pick (and its "Your location") is.
 */
const PLAN_BOX_CHOICE = { from: "start", to: "end", add: "via" } as const satisfies Record<string, PlaceChoice>;
type PlanBox = keyof typeof PLAN_BOX_CHOICE;
const isPlanBox = (variant: string): variant is PlanBox => variant in PLAN_BOX_CHOICE;

/** The "Your location" choice in the list, ahead of the places found. */
const HERE = "here" as const;

/** A place's "Make this the destination" row (v0.7.0, "Keep adding stops by search"), under the place. */
interface AsDestination {
  destination: Place;
}

/** What the result row's second option says. */
export const MAKE_DESTINATION = t("Make this the destination");

const CHOICE_LABEL: Record<PlaceChoice, string> = { start: t("Start"), end: t("Destination"), via: t("Stop") };

export function searchStatus(result: GeoResult | null, query: string): string {
  if (result === null) return "";
  if (!result.ok) {
    return result.status === 429 || result.status === 503
      ? t("Search is busy; keep typing or try again in a moment.")
      : t("Place search is not available right now.");
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
  variant = "plan",
  onTopPlace,
  current,
  inputRef,
  onDismiss,
  onFocusBox,
}: {
  /**
   * "plan": the Points search, with Start / Destination / Stop. "go" (UI-CLEANUP): Go's one Where to? box,
   * whose place is the destination, from the rider's location. "home": My Go's Home, a place and no more.
   * "work" and "favorite": Go's Favorites popout (lib/favoritePlaces.ts), Work or another favorite place.
   */
  variant?: "plan" | "go" | "home" | "work" | "favorite" | "start" | "stop" | PlanBox;
  /** Absent: no "Use my location" (a test or a build without it). */
  locate?: LocateControl;
  /** "Make it a loop" is on: a place is the start or a stop, never a destination (OWNER-DECISIONS 374). */
  loop?: boolean;
  pointCount: number;
  /** The plan has as many points as a route can take. */
  full: boolean;
  gate: GeoGate;
  /** Where results should lean towards: the rider's known location (rounded) while it is in view, else the map's centre; none outside the area (lib/geocode.ts searchBiasPoint). */
  bias: () => LonLat | undefined;
  onPick: (place: Place, choice: PlaceChoice) => void;
  /**
   * The first place listed, each time another leads the list (Go's early start; v0.7.0, "Faster routing"); null when
   * none does any more (the box cleared, or no results), so a wait for the last one is dropped.
   */
  onTopPlace?: (place: Place | null) => void;
  /** Plan's From and To: the place the box changes, named under its label ("Now: Union Station"), or absent. */
  current?: string;
  /** A ref to the input, so a "Change" can put the focus in the box. */
  inputRef?: RefObject<HTMLInputElement | null>;
  /** Escape on an empty box (Plan's From or To while changing a point): the box is put away. */
  onDismiss?: () => void;
  /** The box takes the focus (Go's Where to?: a warm look-up of the location; routing audit S28). */
  onFocusBox?: () => void;
}) {
  const id = useId();
  const single = variant !== "plan";
  const planBox = isPlanBox(variant) ? variant : null;
  const boxChoice: PlaceChoice | undefined = planBox ? PLAN_BOX_CHOICE[planBox] : undefined;
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<GeoResult | null>(null);
  const [answered, setAnswered] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  // What the rider asked a pick to be; null until they choose, which follows
  // the plan (the start of an empty plan, then the destination).
  const [chosen, setChosen] = useState<PlaceChoice | null>(null);
  // A pasted link or typed coordinates: the place read from it, the link being opened, or why not.
  const [shared, setShared] = useState<{ place: Place } | { said: string } | null>(null);
  const sharedTurn = useRef(0);
  // The last places picked in any search box, read again on focus so a pick in another box shows.
  const [recent, setRecent] = useState<Place[]>(() => readRecentPlaces());
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
  // On a phone, while the box has the focus: the app is shortened by what the keyboard covers (iOS;
  // lib/keyboardLift.ts, review UI-7), so the results in the sheet are not under it.
  const keyboardWatch = useRef<(() => void) | null>(null);
  const stopKeyboardWatch = () => {
    keyboardWatch.current?.();
    keyboardWatch.current = null;
  };
  useEffect(() => stopKeyboardWatch, []);

  const { places, answeredNow, searching, choices, choice, effect } = searchView({
    query,
    answered,
    result,
    open,
    pointCount,
    full,
    chosen: chosen ?? boxChoice ?? null,
    loop,
  });
  // "Your location" leads the list while the box is empty or says so; it is never the Enter default.
  const showHere = locate?.support.available === true && locationMatches(query);
  // A pick that adds a stop (Plan with a start and an end) offers the place as the destination too, on a row
  // of its own under it, so it is an option a keyboard and a screen reader reach like any other.
  // Plan's Add a stop keeps it too (Plan streamline). In a loop it ends the loop there (the owner, 2026-10-22).
  const offersDestination = (variant === "plan" || variant === "add") && effect === "via";
  const sharedItems: Place[] = shared && "place" in shared ? [shared.place] : [];
  const sharedSaid = shared && "said" in shared ? shared.said : "";
  // The empty box lists the last places picked (v0.6.1), under "Your location".
  const empty = query.trim() === "";
  const offered: Place[] = [...sharedItems, ...(empty ? recent : places)];
  // What Enter with nothing highlighted takes: the first place offered for the words typed; an empty box
  // takes nothing (a recent place is picked only by choosing it).
  const enterPlaces: Place[] = empty ? [] : offered;
  // The place Enter would take: Go starts routing there while the rider looks (the same place, always).
  const top = enterPlaces[0] ?? null;
  const onTopPlaceNow = useRef(onTopPlace);
  onTopPlaceNow.current = onTopPlace;
  // Null once when a listed place goes (the box cleared, no results), not on opening with nothing typed.
  const toldTop = useRef(false);
  useEffect(() => {
    if (top || toldTop.current) onTopPlaceNow.current?.(top);
    toldTop.current = top !== null;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per place listed first, not per render
  }, [top?.lon, top?.lat, top?.name]);
  const listed: (Place | AsDestination)[] = offersDestination ? offered.flatMap((place) => [place, { destination: place }]) : offered;
  const items: (Place | AsDestination | typeof HERE)[] = showHere ? [HERE, ...listed] : listed;
  const expanded = open && items.length > 0;
  const listId = `${id}-list`;
  const optionId = (i: number) => `${id}-opt-${i}`;

  const change = (value: string) => {
    setQuery(value);
    setOpen(true);
    sharedTurn.current += 1;
    // Coordinates typed or a whole link pasted in: the place it holds, offered first.
    const found = parseShared(value);
    if (found) {
      openShared(value);
      return;
    }
    setShared(null);
    if (value.trim().length < MIN_QUERY_CHARS) {
      runner.current?.clear();
      setResult(null);
    } else {
      runner.current?.request(value);
    }
  };

  // A link or coordinates: read here, or (a short link) followed by the server; an address is searched for.
  const openShared = (text: string) => {
    const turn = ++sharedTurn.current;
    runner.current?.clear();
    setResult(null);
    setOpen(true);
    const found = parseShared(text);
    if (found?.kind === "point") {
      setShared({ place: sharedPlace(found.point, found.name) });
      return;
    }
    setShared({ said: SHARED_OPENING });
    void readShared(text).then((read) => {
      if (turn !== sharedTurn.current) return;
      if ("place" in read) setShared({ place: read.place });
      else if ("query" in read) {
        setShared(null);
        setQuery(read.query);
        runner.current?.request(read.query);
      } else setShared({ said: read.error });
    });
  };

  const pick = (place: Place, as?: PlaceChoice) => {
    onPick(place, as ?? boxChoice ?? (variant === "stop" ? "via" : single ? "end" : choice));
    sharedTurn.current += 1;
    setShared(null);
    // A Home is not a recent place: it would outlast Clear Home and sign-out on a shared phone (review privacy-1).
    // Nor is Work, or a favorite: they are the account's.
    if (variant !== "home" && variant !== "work" && variant !== "favorite") setRecent(rememberRecentPlace(place));
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
    locate?.onLocate(boxChoice ?? choice);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const action = comboboxKey(event.key, {
      active,
      count: items.length,
      expanded,
      hasQuery: query !== "",
    });
    // Escape on an empty, closed box opened by a Change puts the box away (Plan streamline).
    if (event.key === "Escape" && query === "" && !expanded && onDismiss) {
      event.preventDefault();
      onDismiss();
      return;
    }
    if (action.kind === "none") return;
    event.preventDefault();
    if (action.kind === "move") {
      setOpen(true);
      setActive(action.active);
    } else if (action.kind === "pick") {
      // Enter with nothing highlighted takes the first place for the words typed (the top place), never "Your
      // location" (a look-up asks the browser's permission) and never a recent place from an empty box.
      const item = pickTarget(active, action.index, items, enterPlaces);
      if (item === HERE) pickHere();
      else if (item && "destination" in item) pick(item.destination, "end");
      else if (item) pick(item);
    } else if (action.kind === "close") {
      setOpen(false);
      setActive(-1);
    } else {
      change("");
    }
  };

  return (
    <div className={variant === "go" ? "place-search go-search" : "place-search"}>
      <label htmlFor={`${id}-input`} className={variant === "go" ? "place-search-label visually-hidden" : "place-search-label"}>
        {t(variant === "go" ? "Where to?" : variant === "home" ? "Find your Home" : variant === "work" ? "Find your Work" : variant === "favorite" ? "Find a place to save" : variant === "start" ? "Start from" : variant === "stop" || variant === "add" ? "Add a stop" : variant === "from" ? "From" : variant === "to" ? "To" : "Find a place")}
        {current && <span className="place-search-current">{` (now ${current})`}</span>}
      </label>
      <div className={(locate && !locate.listOnly) || variant === "go" ? "place-search-row" : undefined}>
      {variant === "go" && <Icon name="search" className="search-icon" />}
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
        ref={inputRef}
        placeholder={
          t(variant === "go" ? "Where to?" : variant === "start" ? "Type a start" : variant === "stop" || variant === "add" ? "Add a stop" : variant === "from" ? "Search for a start" : variant === "to" ? "Search for a destination" : "A place, an address or a street")
        }
        value={query}
        onChange={(event) => change(event.target.value)}
        onPaste={(event) => {
          // A whole map link, longer than the box takes: read before the box cuts it.
          const text = event.clipboardData.getData("text");
          if (!parseShared(text)) return;
          event.preventDefault();
          setQuery(text.slice(0, MAX_QUERY_CHARS));
          openShared(text);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => {
          setOpen(false);
          stopKeyboardWatch();
        }}
        onFocus={(event) => {
          onFocusBox?.();
          setOpen(true);
          setRecent(readRecentPlaces());
          // On a phone the sheet is half the screen and the keyboard takes
          // much of the rest: bring the box to the top of the sheet so the
          // results under it can be seen.
          if (window.matchMedia(PHONE).matches) {
            stopKeyboardWatch();
            keyboardWatch.current = watchKeyboard(window, document.documentElement);
            event.currentTarget.scrollIntoView({ block: "start" });
          }
        }}
      />
      {locate && !locate.listOnly && (
        <button
          type="button"
          className="secondary locate-button"
          // aria-disabled, not disabled: it stays in the Tab order with its reason as its description,
          // and a press changes nothing while it cannot work. While a look-up is under way a press starts
          // no second one; the app says "Finding your location…" again, so the press gets an answer.
          aria-disabled={!locate.support.available || locate.busy || undefined}
          aria-describedby={!locate.support.available ? `${id}-locate-why` : locate.busy ? `${id}-locate-busy` : undefined}
          onClick={() => {
            if (locate.support.available) locate.onLocate(boxChoice);
          }}
        >
          {t("Use my location")}
        </button>
      )}
      </div>
      {locate && !locate.listOnly && !locate.support.available && (
        <p id={`${id}-locate-why`} className="hint">
          {locate.support.reason}
        </p>
      )}
      {locate && locate.busy && (
        <p id={`${id}-locate-busy`} className="hint">
          {FINDING_LOCATION}
        </p>
      )}
      {/* The located point's note shows under whichever box is open, Add a stop too: a loop has no To box (Plan starts
          as a loop, Stephen 2026-10-20), and the note is what says the point is approximate. */}
      {locate && !locate.busy && locate.note && <p className="hint">{locate.note}</p>}
      <ul id={listId} role="listbox" aria-label={empty ? t("Your location and recent places") : t("Places found")} className="place-results" hidden={!expanded}>
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
              <span className="place-name">{t("Your location")}</span>
              <span className="place-label">{hereEffectLine(effect, loop)}</span>
            </li>
          ) : "destination" in item ? (
            <li
              key={`dest:${item.destination.lon},${item.destination.lat},${item.destination.label}`}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              aria-label={`${MAKE_DESTINATION}: ${item.destination.name}`}
              className={i === active ? "active place-as-destination" : "place-as-destination"}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(item.destination, "end")}
            >
              <span className="place-label">{MAKE_DESTINATION}</span>
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
      {/* Always mounted, filled after (review F10): a status region mounted with its words in it is often not read. */}
      <p className={sharedSaid ? "hint" : "visually-hidden"} role="status" aria-live="polite">
        {sharedSaid}
      </p>
      {expanded && places.length > 0 && (
        <p className="place-credit">
          {t("Only places in this map's area.")}
          {result?.ok && result.attribution.length > 0 && <> Search: {result.attribution.join("; ")}</>}
        </p>
      )}
      {!single && choices.length > 1 && (
        <fieldset className="place-choice">
          <legend>{t("Use the place as")}</legend>
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
      {/* Go's hint is said with the box and kept out of sight, so Go's sheet fits one phone screen (the owner, 2026-10-17). */}
      {/* Go's hint is said with the box and kept out of sight (above); so are Plan's From, To and Add a stop,
          whose labels say what a pick does (Plan streamline): only the full plan's reason shows. */}
      <p id={`${id}-hint`} className={variant === "go" ? "visually-hidden go-from" : planBox ? (full && planBox === "add" ? "hint" : "visually-hidden") : "hint"}>
        {variant === "plan" ? <>{placeEffectHint(effect, loop)}</> : planBox === "from" && loop ? placeEffectHint("start", true) : SINGLE_HINT[variant]}
        {(!single || planBox === "add") && full && " The route has as many points as it can take, so no stop can be added."}
      </p>
      <p className="visually-hidden" role="status" aria-live="polite">
        {answeredNow ? searchStatusWithHere(searchStatus(result, answered), expanded && showHere) : ""}
      </p>
      {searching && <p className="hint">{t("Searching…")}</p>}
      {answeredNow && result && (!result.ok || result.places.length === 0) && (
        <p className="hint">{searchStatus(result, answered)}</p>
      )}
    </div>
  );
}
