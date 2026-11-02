/**
 * The search box: type a place, pick it, and it becomes the start, the
 * destination or a stop, as chosen (lib/geocode.ts, applyPlace). Each result
 * shows a short type from its OSM tag and, with the route's start known, how far it is from there; the places are
 * then nearest first (P2, lib/geocode.ts nearestFirst). The list says it holds only places in this map's area.
 *
 * The ARIA 1.2 combobox pattern: the input owns a listbox, the arrow keys
 * move through the options without leaving the input (aria-activedescendant),
 * Enter picks, Escape closes and then clears. The empty box lists "Your
 * location" and then the last places picked (lib/recentPlaces.ts). The result count is announced
 * in a polite live region, and the options are tall enough to tap.
 *
 * A pasted map link (Google, Apple, Waze, geo:), typed coordinates (decimal, or degrees, minutes and seconds) or a
 * plus code are read as a place (lib/sharedLocation.ts, v0.7.0 "Open shared locations"; lib/plusCode.ts): it leads
 * the list as one option, and a short link is followed by the server first.
 *
 * Go's box has a microphone where speech works (lib/placeDictation.ts, Stephen 2026-10-30): the place said is searched,
 * the places found are lettered (in English and Spanish, lettersHeard), and "B", "Bravo" or a place's name said picks
 * one; other words keep the list.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import {
  COVERS_LINE,
  MAX_QUERY_CHARS,
  MIN_QUERY_CHARS,
  PlaceSearchRunner,
  comboboxKey,
  namesCityOutside,
  nearestFirst,
  nothingFoundText,
  pickTarget,
  placeDistance,
  placeRowLine,
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
import { nativeBridge } from "./lib/nativeShell.ts";
import { SAVED_KINDS, type SavedHits } from "./lib/savedPlaceSearch.ts";
import {
  lettersHeard,
  placeDictation,
  placeSpeechSupported,
  rowLetter,
  sayWhereLabel,
  voiceLine as voiceLineFor,
  type PlaceDictation,
  type PlaceListening,
} from "./lib/placeDictation.ts";

// App.tsx's phone layout, where the panel is a bottom sheet.
const PHONE = "(max-width: 720px)";

/** How long after the lettered places show it starts listening for a letter (a screen reader says the line first). */
const ROW_LISTEN_DELAY_MS = 1500;

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

export function searchStatus(result: GeoResult | null, query: string, saved = 0): string {
  if (result === null) return "";
  if (!result.ok) {
    return result.status === 429 || result.status === 503
      ? t("Search is busy; keep typing or try again in a moment.")
      : t("Place search is not available right now.");
  }
  // Home, Work and favorites matched by name are listed above the search's places, so they count too.
  const count = result.places.length + saved;
  if (count === 0) return nothingFoundText(query);
  const found = count === 1 ? t("1 place found.") : t("{count} places found.", { count });
  return namesCityOutside(query) ? `${found} ${COVERS_LINE}` : found;
}

/**
 * A result's second line (P2): "Dupont Circle, Washington · 0.7 mi (1.1 km)". A screen reader hears the distance as
 * words, "…, 0.7 mi (1.1 km) away in a straight line"; the dot and the bare figure are for the eye.
 */
function PlaceRowLine({ place, start }: { place: Place; start: LonLat | undefined }) {
  const line = placeRowLine(place, start);
  if (line === "") return null;
  if (!start) return <span className="place-label">{line}</span>;
  const area = placeRowLine(place, undefined);
  const said = t("{distance} away in a straight line", { distance: placeDistance(place, start) });
  return (
    <span className="place-label">
      <span aria-hidden="true">{line}</span>
      <span className="visually-hidden">{area ? `${area}, ${said}` : said}</span>
    </span>
  );
}

export function PlaceSearch({
  pointCount,
  full,
  gate,
  bias,
  origin,
  onPick,
  loop = false,
  locate,
  variant = "plan",
  onTopPlace,
  current,
  inputRef,
  onDismiss,
  onFocusBox,
  savedFor,
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
  /**
   * The route's start (Go: the rider's location or the start typed in; Plan: the first point): the places found are
   * listed nearest it first, each with its distance (P2). Absent, or none known: the server's order, no distances.
   */
  origin?: () => LonLat | undefined;
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
  /** Go's Where to?: the rider's Home, Work and favorites the words name (lib/savedPlaceSearch.ts), listed first. */
  savedFor?: (query: string) => SavedHits;
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

  // Say where to (Go only): the microphone shows where speech works and hears the language in force.
  const [canSay] = useState(() => variant === "go" && placeSpeechSupported());
  const [listening, setListening] = useState<PlaceListening>(null);
  const [voiceNote, setVoiceNote] = useState("");
  // The words last searched by voice: while the box still holds them, the places found are lettered.
  const [spoken, setSpoken] = useState<string | null>(null);
  // The lettered places, for a row named while the list shows (filled each render, below).
  const letteredNow = useRef<Place[]>([]);
  const pickNow = useRef<(place: Place) => void>(() => {});
  const savedForNow = useRef(savedFor);
  savedForNow.current = savedFor;
  const changeNow = useRef<(value: string) => void>(() => {});
  const dictation = useRef<PlaceDictation | null>(null);
  if (canSay && dictation.current === null) {
    dictation.current = placeDictation(
      {
        listening: setListening,
        text: (words) => {
          setQuery(words);
          setOpen(true);
        },
        search: (words) => {
          // "Home", "work" or a favorite's name, said: routed there at once, as its chip would.
          const exact = savedForNow.current?.(words).exact;
          if (exact && boxShown()) {
            pickNow.current(exact);
            return;
          }
          setSpoken(words);
          changeNow.current(words);
        },
        pick: (row) => {
          // Only a row the rider can see: the box may have been put away while it listened.
          const place = letteredNow.current[row];
          if (place && boxShown()) pickNow.current(place);
        },
        note: setVoiceNote,
      },
      MAX_QUERY_CHARS,
    );
  }
  useEffect(() => () => dictation.current?.abort(), []);
  // Go hides the box (New destination folded) without unmounting it: speech stops with it.
  const boxRef = useRef<HTMLDivElement>(null);
  const boxShown = () => (boxRef.current?.getClientRects().length ?? 0) > 0;
  const quiet = () => {
    dictation.current?.abort();
    setSpoken(null);
    setVoiceNote("");
  };
  const quietNow = useRef(quiet);
  quietNow.current = quiet;
  useEffect(() => {
    const box = boxRef.current;
    if (!canSay || !box || typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(() => {
      if (box.getClientRects().length === 0) quietNow.current();
    });
    watch.observe(box);
    return () => watch.disconnect();
  }, [canSay]);

  const { places: found, answeredNow, searching, choices, choice, effect } = searchView({
    query,
    answered,
    result,
    open,
    pointCount,
    full,
    chosen: chosen ?? boxChoice ?? null,
    loop,
  });
  // Nearest the start first (P2); Enter and Go's early start take the same first place the list shows.
  const start = origin?.();
  const places = nearestFirst(found, start, answered);
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
  const saved: Place[] = savedFor && !empty ? savedFor(query).places : [];
  const offered: Place[] = [...sharedItems, ...(empty ? recent : [...saved, ...places])];
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
  // Places found for words said: lettered A, B, C, so a letter said picks one; only where letters are heard
  // (lettersHeard: en, es), else the rider taps a place and the microphone listens for a place again.
  const lettered: Place[] = canSay && lettersHeard() && spoken !== null && query === spoken && answered === spoken && !empty ? offered : [];
  letteredNow.current = lettered;
  // Listen for the letter once the places for the words said are listed; not in the phone app, whose speech input
  // covers the list while it listens (the rider taps the microphone to say the letter).
  const askedRow = useRef("");
  const rowWait = useRef<number | undefined>(undefined);
  const rowsKey = lettered.map((place) => place.label).join("|");
  // It waits a moment, so a screen reader can read the list first. The wait does not keep its reading of the line
  // ("Listening. Say a letter…", set only once listening starts) from being heard: placeDictation keeps the list for
  // any words that name no row, so such an echo says no letter was heard and never replaces the places.
  useEffect(() => {
    if (lettered.length === 0 || !expanded || listening !== null || askedRow.current === rowsKey || nativeBridge()) return;
    askedRow.current = rowsKey;
    const wait = (rowWait.current = window.setTimeout(() => {
      if (boxShown() && letteredNow.current.length > 0) dictation.current?.start(letteredNow.current.map((place) => place.name));
    }, ROW_LISTEN_DELAY_MS));
    return () => window.clearTimeout(wait);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per lettered list
  }, [rowsKey, expanded]);
  // The list closed (the box lost the focus): no listening for a letter the rider cannot see.
  useEffect(() => {
    if (!expanded && listening === "row") dictation.current?.abort();
  }, [expanded, listening]);
  const listId = `${id}-list`;
  const optionId = (i: number) => `${id}-opt-${i}`;

  // Where a short plus code ("VXQ7+GV") is placed: the route's start, else the search's bias (the location or the
  // map's view); the middle of the map without either (lib/plusCode.ts).
  const near = () => origin?.() ?? bias();

  const change = (value: string) => {
    setQuery(value);
    setOpen(true);
    sharedTurn.current += 1;
    // Coordinates or a plus code typed, or a whole link pasted in: the place it holds, offered first.
    const found = parseShared(value, near());
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

  // A link, coordinates or a plus code: read here, or (a short link) followed by the server; an address is searched for.
  const openShared = (text: string) => {
    const turn = ++sharedTurn.current;
    runner.current?.clear();
    setResult(null);
    setOpen(true);
    const found = parseShared(text, near());
    if (found?.kind === "point") {
      setShared({ place: sharedPlace(found.point, found.name, found.typed) });
      return;
    }
    setShared({ said: SHARED_OPENING });
    void readShared(text, undefined, near()).then((read) => {
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
    dictation.current?.abort();
    setSpoken(null);
    setVoiceNote("");
    onPick(place, as ?? boxChoice ?? (variant === "stop" ? "via" : single ? "end" : choice));
    sharedTurn.current += 1;
    setShared(null);
    // A Home is not a recent place: it would outlast Clear Home and sign-out on a shared phone (review privacy-1).
    // Nor is Work, or a favorite: they are the account's.
    // Nor a saved place picked in Go's Where to? (lib/savedPlaceSearch.ts).
    if (variant !== "home" && variant !== "work" && variant !== "favorite" && !SAVED_KINDS.has(place.kind)) setRecent(rememberRecentPlace(place));
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

  pickNow.current = pick;
  changeNow.current = change;

  const sayWhere = () => {
    // A tap before the letter listen starts is the rider's own: the wait is dropped, not run over it.
    window.clearTimeout(rowWait.current);
    if (listening) {
      dictation.current?.stop();
      return;
    }
    dictation.current?.start(expanded ? lettered.map((place) => place.name) : []);
  };
  const voiceLine = voiceLineFor(listening, voiceNote, lettered.length > 0 && expanded);

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
      if (canSay) quiet();
      change("");
    }
  };

  return (
    <div ref={boxRef} className={variant === "go" ? (canSay ? "place-search go-search can-say" : "place-search go-search") : "place-search"}>
      {/* Go's Where to? and Add a stop say their names in the box (and Add a stop on the button that opens it). */}
      <label htmlFor={`${id}-input`} className={variant === "go" || variant === "stop" ? "place-search-label visually-hidden" : "place-search-label"}>
        {t(variant === "go" ? "Where to?" : variant === "home" ? "Find your Home" : variant === "work" ? "Find your Work" : variant === "favorite" ? "Find a place to save" : variant === "start" ? "Start from" : variant === "stop" || variant === "add" ? "Add a stop" : variant === "from" ? (loop ? "Start and finish (loop)" : "From") : variant === "to" ? "To" : "Find a place")}
        {current && <span className="place-search-current">{` ${t("(now {place})", { place: current })}`}</span>}
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
        onChange={(event) => {
          // Typing takes over from speech: the letters go and the microphone stops.
          if (canSay) quiet();
          change(event.target.value);
        }}
        onPaste={(event) => {
          // A whole map link, longer than the box takes: read before the box cuts it.
          const text = event.clipboardData.getData("text");
          if (!parseShared(text, near())) return;
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
      {canSay && (
        <button
          type="button"
          className="say-where"
          aria-label={sayWhereLabel()}
          aria-pressed={listening !== null}
          // Before the input's blur, which would close the list first.
          onMouseDown={(event) => event.preventDefault()}
          onClick={sayWhere}
        >
          <Icon name="mic" size={22} />
        </button>
      )}
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
      {canSay && (
        <p className={voiceLine ? "hint say-where-line" : "visually-hidden"} role="status" aria-live="polite">
          {voiceLine}
        </p>
      )}
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
              className={[i === active ? "active" : "", lettered.length > 0 ? "lettered" : ""].filter(Boolean).join(" ") || undefined}
              // Before the input's blur, which would close the list first.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(item)}
            >
              {lettered.length > 0 && <span className="row-letter">{rowLetter(lettered.indexOf(item))}<span className="visually-hidden">, </span></span>}
              <span className="place-name">
                {item.name} <span className="place-type">{placeType(item)}</span>
              </span>
              {/* The last places picked (an empty box) show no distance: they are not answers to a search. */}
              <PlaceRowLine place={item} start={empty ? undefined : start} />
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
          {result?.ok && result.attribution.length > 0 && <> {t("Search: {credits}", { credits: result.attribution.join("; ") })}</>}
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
      {/* Go's hint is said with the box and kept out of sight, so Go's sheet fits one phone screen (the owner, 2026-10-17);
          so are those of Go's other boxes, whose labels say what a pick does (the owner's P1, 2026-10-28: Add a stop's,
          the start's, Home's and Favorites'), and Plan's From, To and Add a stop's (Plan streamline): only the full
          plan's reason shows. */}
      <p id={`${id}-hint`} className={variant === "go" ? "visually-hidden go-from" : planBox ? (full && planBox === "add" ? "hint" : "visually-hidden") : variant === "plan" ? "hint" : "visually-hidden"}>
        {variant === "plan" ? <>{placeEffectHint(effect, loop)}</> : planBox === "from" && loop ? placeEffectHint("start", true) : SINGLE_HINT[variant]}
        {(!single || planBox === "add") && full && ` ${t("The route has as many points as it can take, so no stop can be added.")}`}
      </p>
      <p className="visually-hidden" role="status" aria-live="polite">
        {answeredNow ? searchStatusWithHere(searchStatus(result, answered, saved.length), expanded && showHere) : ""}
      </p>
      {searching && <p className="hint">{t("Searching…")}</p>}
      {answeredNow && expanded && places.length > 0 && namesCityOutside(answered) && <p className="hint">{COVERS_LINE}</p>}
      {answeredNow && result && (!result.ok || result.places.length + saved.length === 0) && (
        <p className="hint">{searchStatus(result, answered, saved.length)}</p>
      )}
    </div>
  );
}
