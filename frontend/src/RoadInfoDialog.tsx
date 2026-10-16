/**
 * The map's road panel (OWNER-DECISIONS 441, 441a; lib/roadInfo.ts): what RouteMaker
 * knows of the road or path nearest a spot, with a bottom row of links drawn as
 * buttons: Street View, Edit in OSM, and, for an instance admin, Change LTS (OWNER-DECISIONS 441g, 441h,
 * 441m), which opens the stress editor (StressEditor.tsx) in this same dialog in place of the row.
 *
 * Compact, so the common case fits a phone without scrolling: the name, its kind, a
 * short summary list (one line a fact, read in order), a nearby station's pages and its
 * lines' times now (scheduled; lib/stationTimes.ts, as the station's card on the map says them), a
 * closed native "Details and sources" disclosure with every figure, its source in words,
 * the owner's rating, the way's id and its distance, and the action row.
 *
 * The platform's own modal `<dialog>`, as the ride-type picker is: it makes the rest of
 * the page inert while open, Escape closes it, and Tab is held inside it. On open the
 * focus goes to its heading, so a screen reader says what it is about first; on close
 * it goes back to whatever opened it (the map, or the Road info button). The summary is
 * a list; in the details each part is a labelled section with a heading, the figures a
 * description list; nothing depends on colour. The answer is also said, in one short
 * sentence, through a polite status region inside the dialog itself (always rendered,
 * empty until the answer comes, as the weight dialog's total is), so a rider who stays on
 * the heading hears it come in: the page's own region is outside the modal, which makes it
 * inert and drops it from the accessibility tree (the a11y review's S1).
 *
 * On an Avoid-rated junction the route passes (FOLLOWUP-ISECT-AVOID; the owner, 2026-10-10
 * 15:08 UTC: "Yes, also when clicking on the intersection. ... Basically something to say: this
 * is a really bad idea, please reconsider.") the panel leads with a warning, above its heading,
 * and it opens the dialog's description (`aria-describedby`), so it is said as the panel opens.
 * Not also an alert: the two together were said twice (the review of 351e65b).
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  DETAILS_TEXT,
  NO_ROAD_HINT,
  OSM_EDIT_NOTE,
  OSM_EDIT_TEXT,
  spotActions,
  STREET_VIEW_NOTE,
  STREET_VIEW_TEXT,
  fetchSegmentInfo,
  streetViewPoint,
  infoHeading,
  infoSaid,
  moreLink,
  refreshedSaid,
  osmEditUrl,
  shownSections,
  shownSummary,
  streetViewUrl,
  subtitle,
  valueParts,
  wayRows,
  type InfoRequest,
  type InfoState,
} from "./lib/roadInfo.ts";
import type { PlaceChoice } from "./lib/geocode.ts";
import { SET_AS_HOME_TEXT } from "./lib/homeSet.ts";
import { stationLinks } from "./lib/stationLinks.ts";
import { TIMES_LABEL, requestStationTimes, stationCardRows } from "./lib/stationTimes.ts";
import type { StationTimes } from "./lib/api.ts";
import { WMATA_SLUGS } from "./lib/railData.ts";
import type { RailVisibility, Station } from "./lib/railStations.ts";
import { StressPageLink } from "./lib/stressLegend.ts";
import { closesDialog, nextFocus, tabStops, type TabCandidate } from "./lib/rideTypeDialog.ts";
import { CHANGE_LTS_TEXT, NO_ME, fetchMe, type Me } from "./lib/stressEditor.ts";
import { StressEditor } from "./StressEditor.tsx";
import { SuggestChange } from "./SuggestChange.tsx";
import { SuggestQuick } from "./SuggestQuick.tsx";
import { SUGGEST_TEXT, fetchMySuggestion, mySuggestionText, type MySuggestion } from "./lib/suggestions.ts";
import { NO_PHOTO_TEXT, fetchStreetPhoto, photoAlt, type PhotoAnswer } from "./lib/streetPhoto.ts";

/** The one button that holds the ways to suggest, when there are two or more (UI-CLEANUP). */
export const SUGGEST_MENU_TEXT = "Suggest a change…";
import { SuggestJunction } from "./SuggestJunction.tsx";
import { JUNCTION_SUGGEST_TEXT, findJunction, junctionNote, type JunctionAt, type Shown } from "./lib/junctionSuggest.ts";
import { AVOID_CARD_HEADING, AVOID_SYMBOL, avoidCardText, type AvoidItem } from "./lib/avoidJunctions.ts";
import { FEDERAL_ADVICE, stopWarningShort, type FederalArea } from "./lib/federalStops.ts";
import { HazardReport } from "./HazardReport.tsx";
import { ClosureEntry } from "./ClosureEntry.tsx";
import { MARK_CLOSED_TEXT } from "./lib/closureReview.ts";
import { climbLabel, type Climb } from "./lib/climbs.ts";
import { CLIMB_DETAILS_TEXT } from "./lib/climbCard.ts";
import { HAZARD_REPORT_TEXT, hazardOnPiece, hazardPanelText, hazardSaid, type HazardCollection } from "./lib/massHazards.ts";

interface Props {
  /** The spot asked about, or null while the panel is closed. */
  request: InfoRequest | null;
  /**
   * A Mass Ride's approved rider-marked hazards (lib/massHazards.ts; FOLLOWUP-MASSRIDE-MAP part 3): the
   * panel names the one on its road and offers Mark a hazard. Null or absent on every other ride type (325).
   */
  hazards?: HazardCollection | null;
  /** The Mass Ride map is showing: its capacity section shows too. */
  massRide: boolean;
  /** A station near the spot whose pages the panel offers, or null. */
  station: Station | null;
  /** The map's rail toggles: a station's times show the lines of the systems shown, as its card does. */
  rail?: RailVisibility;
  /** Why a station is closed all day, or null (railClosures.ts): a closed station shows no times, as its card. */
  stationClosed?: (station: Station) => string | null;
  /** An Avoid-rated junction on the route near the spot (avoidNearSpot), which the panel warns of first; null where none. */
  avoid?: AvoidItem | null;
  /**
   * What the rider's route shows at the junction nearest the spot (lib/junctionSuggest.ts shownNear): its
   * marker, "none", or null with no route. The junction suggestion form says it and sends it.
   */
  junctionShown?: Shown | null;
  /**
   * On a Mass Ride, the federal area the spot is in (lib/federalStops.ts federalAreaAt; item 239), or
   * null: the keyboard's and screen reader's way to learn what a shaded area is, at the map's center.
   */
  federal?: FederalArea | null;
  /**
   * The Climbs layer's climb at the spot, while the layer is on (lib/climbCard.ts climbNearSpot), or null: the
   * keyboard's way to a climb's card ("Climb details", which closes the panel and opens the card, focused).
   */
  climb?: Climb | null;
  onShowClimb?: (climb: Climb) => void;
  /** The dialog closed while showing `closed` (the App keeps a newer request: requestAfterClose). */
  onClose: (closed: InfoRequest | null) => void;
  /**
   * Where the focus goes on close when whatever opened the panel cannot take it back (a
   * long press leaves the focus on the page itself): the map (the a11y review's N6).
   */
  fallbackFocus?: () => HTMLElement | null;
  /**
   * An instance admin changed (or undid a change of) a road's stress (OWNER-DECISIONS 441h): the
   * map asks for its tiles again under the new edit generation. The panel refreshes itself.
   */
  onStressChanged?: (generation: number) => void;
  /** The plan's point count and whether it is a loop, for the top row (OWNER-DECISIONS 441n). */
  plan: { count: number; loop: boolean };
  /** Put the spot in the plan as its start, its end or a stop; the panel then closes. */
  onPlace: (choice: PlaceChoice, point: [number, number]) => void;
  /** "Set as Home" (lib/homeSet.ts): the spot is the rider's Home; the panel then closes. Absent: no button. */
  onSetHome?: (point: [number, number]) => void;
}

const FOCUSABLE =
  "button:not([disabled]), [href], summary, input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

/** Whether an element is shown and so can take the focus (`checkVisibility` sees a closed fold). */
function isShown(el: HTMLElement): boolean {
  const check = (el as HTMLElement & { checkVisibility?: () => boolean }).checkVisibility;
  return typeof check === "function" ? check.call(el) : el.getClientRects().length > 0;
}

/** The stop after (or before) `from` in page order among `items`, wrapping round at the ends. */
function neighbour(items: HTMLElement[], from: HTMLElement, backwards: boolean): HTMLElement {
  if (backwards) {
    const before = items.filter((i) => from.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_PRECEDING);
    return before.length ? before[before.length - 1] : items[items.length - 1];
  }
  const after = items.filter((i) => from.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING);
  return after.length ? after[0] : items[0];
}

/** Both rail systems shown: where the panel is not told the map's toggles. */
const ALL_RAIL: RailVisibility = { metro: true, marc: true };

/**
 * A nearby station's lines now, scheduled, as its card on the map says them (railInteraction.ts): the
 * lines of the systems the map shows, and none for a station closed all day. The emoji and short words
 * are aria-hidden; the words are said in full.
 */
function StationTimesList({ station, rail, closed }: { station: Station; rail: RailVisibility; closed: boolean }) {
  const [times, setTimes] = useState<StationTimes | null>(null);
  const [lon, lat] = station.point;
  useEffect(() => {
    let live = true;
    setTimes(null);
    if (closed) return;
    void requestStationTimes([lon, lat]).then((answer) => {
      if (live) setTimes(answer);
    });
    return () => {
      live = false;
    };
  }, [lon, lat, closed]);
  const rows = !closed ? stationCardRows(times, rail) : [];
  if (rows.length === 0) return null;
  return (
    <ul className="station-times road-info-times" aria-label={TIMES_LABEL}>
      {rows.map((row) => (
        <li key={row.key}>
          <span aria-hidden="true">{row.shown}</span>
          <span className="visually-hidden">{row.spoken}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The road's street photo (v0.7.0; lib/streetPhoto.ts): the newest Mapillary photo facing along the road,
 * a link to Mapillary's viewer in a new tab, its date under it and in its alt text, and the credit. One
 * plain line where Mapillary has none; nothing where the server cannot look one up.
 */
function StreetPhotoView({ title, point, wayId }: { title: string; point: [number, number]; wayId: number | null }) {
  const [photo, setPhoto] = useState<PhotoAnswer>(null);
  const [lon, lat] = point;
  useEffect(() => {
    const controller = new AbortController();
    setPhoto(null);
    void fetchStreetPhoto(window.location.origin, [lon, lat], wayId, controller.signal).then((answer) => {
      if (!controller.signal.aborted) setPhoto(answer);
    });
    return () => controller.abort();
  }, [lon, lat, wayId]);
  if (photo === null) return null;
  if (photo === "none") return <p className="hint road-info-photo-none">{NO_PHOTO_TEXT}</p>;
  return (
    <figure className="road-info-photo">
      <a href={photo.viewer_url} target="_blank" rel="noopener noreferrer">
        <img src={photo.image_url} alt={photoAlt(title, photo)} width={1024} height={768} loading="lazy" referrerPolicy="no-referrer" />
        <span className="visually-hidden"> (opens Mapillary in a new tab)</span>
      </a>
      <figcaption className="hint">
        {photo.date_words}
        {photo.creator ? `, by ${photo.creator}` : ""} ·{" "}
        <a href={photo.credit_url} target="_blank" rel="noopener noreferrer">
          {photo.credit}
        </a>{" "}
        (
        <a href={photo.licence_url} target="_blank" rel="noopener noreferrer">
          {photo.licence}
        </a>
        )
      </figcaption>
    </figure>
  );
}

export function RoadInfoDialog({ request, hazards = null, massRide, station, rail = ALL_RAIL, stationClosed, avoid = null, junctionShown = null, federal = null, climb = null, onShowClimb, onClose, fallbackFocus, onStressChanged, plan, onPlace, onSetHome }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnTo = useRef<Element | null>(null);
  // The request the dialog was last opened (or moved) for, which a `close` event closes.
  const shown = useRef<InfoRequest | null>(null);
  // Whether the press of the click now arriving went down on the backdrop itself. A finger held
  // on the map opens the panel under it, and its lift can come as a click on the new backdrop;
  // that press began on the map, so it does not close what it just opened.
  const pressedBackdrop = useRef(false);
  const [state, setState] = useState<InfoState>({ kind: "loading" });
  // The answer's sentence for the dialog's own status region, empty until it comes.
  const [said, setSaid] = useState("");
  // Who is asking (three yes/no flags, once per page) and whether the stress editor is open.
  const [me, setMe] = useState<Me>(NO_ME);
  // The federal area's sentence, read when the answer comes (the prop is the spot's, set with the request).
  const federalSaid = federal ? stopWarningShort(federal) : "";
  const federalSaidRef = useRef(federalSaid);
  federalSaidRef.current = federalSaid;
  // The request `state` holds the answer for: null while it is loading, so a late area is never
  // said with the previous spot's road.
  const stateFor = useRef<InfoRequest | null>(null);
  const [editing, setEditing] = useState(false);
  // A rider's "Suggest a change" form (OWNER-DECISIONS 441h; SuggestChange.tsx), open in place of the row.
  const [suggesting, setSuggesting] = useState(false);
  // Whether the account answer is in: the short form (v0.7.0) waits for it, so a rider who may use the
  // full form never sees the short one flash first.
  const [meKnown, setMeKnown] = useState(false);
  // The rider's own latest suggestion for this road and its status (v0.7.0), or null.
  const [mySuggestion, setMySuggestion] = useState<MySuggestion | null>(null);
  const suggestButton = useRef<HTMLButtonElement>(null);
  const returnToSuggest = useRef(false);
  // The junction at the spot, for a rider who may suggest (OWNER-DECISIONS 232; SuggestJunction.tsx): its
  // node from the API, asked only for such a rider, and whether its form is open in place of the row.
  const [junction, setJunction] = useState<JunctionAt | null>(null);
  const [suggestingJunction, setSuggestingJunction] = useState(false);
  // UI-CLEANUP (the mockup's control table): two or more ways to suggest are one "Suggest a change…" button
  // that shows them; open, it stays open while a form opened from it is shown, so Back finds its button.
  const [suggestMenu, setSuggestMenu] = useState(false);
  const suggestMenuId = useId();
  const junctionButton = useRef<HTMLButtonElement>(null);
  const returnToJunction = useRef(false);
  // A Mass Ride's "Mark a hazard" form (HazardReport.tsx), open in place of the row.
  const [reporting, setReporting] = useState(false);
  const hazardButton = useRef<HTMLButtonElement>(null);
  const returnToHazard = useRef(false);
  // A reviewer's "Mark closed" (v0.7.0 closures; ClosureEntry.tsx), open in place of the row.
  const [closing, setClosing] = useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const returnToClosing = useRef(false);
  // The hazards as they are when the answer comes, read inside its callback.
  const hazardsRef = useRef(massRide ? hazards : null);
  hazardsRef.current = massRide ? hazards : null;
  // Bumped after a change or an undo: the answer is fetched again, fresh, without closing the editor.
  const [reload, setReload] = useState(0);
  const changeButton = useRef<HTMLButtonElement>(null);
  const returnToButton = useRef(false);
  const base = useId();
  const id = (part: string) => `${base}-${part}`;

  // Open (or move to a new spot), ask the API, and close when the request goes.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!request) {
      if (dialog.open) dialog.close();
      return;
    }
    if (!dialog.open) {
      returnTo.current = document.activeElement;
      pressedBackdrop.current = false;
      dialog.showModal?.();
    }
    shown.current = request;
    headingRef.current?.focus();
    stateFor.current = null;
    setState({ kind: "loading" });
    setSaid("");
    setEditing(false);
    setSuggesting(false);
    setReporting(false);
    setClosing(false);
    setJunction(null);
    setSuggestingJunction(false);
    setSuggestMenu(false);
    setReload(0);
    const controller = new AbortController();
    void fetchMe(window.location.origin).then((who) => {
      setMe(who);
      setMeKnown(true);
      // Only a rider who may suggest asks where the junction is (nobody else asks the endpoint anything).
      if (!who.can_suggest || controller.signal.aborted) return;
      void findJunction(window.location.origin, request.point, controller.signal).then((found) => {
        if (controller.signal.aborted) return;
        setJunction(found);
        // From a junction card's Suggest a change: its form opens at once.
        if (found && request.junction) setSuggestingJunction(true);
      });
    });
    fetchSegmentInfo(window.location.origin, request.point, controller.signal).then(
      (next) => {
        stateFor.current = request;
        setState(next);
        // The spot's federal area, after the road, in the same status sentence (item 239), and a Mass
        // Ride's rider-marked hazard on the road (325), so it is heard with the road.
        const hazard = hazardSaid(hazardOnPiece(hazardsRef.current, next.kind === "ready" && next.info.found ? next.info : null));
        setSaid([infoSaid(next), hazard, federalSaidRef.current].filter(Boolean).join(" "));
      },
      () => undefined,
    );
    return () => controller.abort();
    // Each request is its own object (App sets a new one per ask), so asking again at the
    // same spot - Escape, then I on an unmoved map - opens the panel again.
  }, [request]);

  // The answer again, fresh, after a change: the editor stays open and keeps the focus.
  useEffect(() => {
    if (reload === 0 || !request) return;
    const controller = new AbortController();
    fetchSegmentInfo(window.location.origin, request.point, controller.signal, true).then(
      (next) => {
        if (next.kind === "ready") setState(next);
      },
      () => undefined,
    );
    return () => controller.abort();
    // `request` is the spot this reload is for; a new spot resets `reload` to 0 above.
  }, [reload]); // eslint-disable-line react-hooks/exhaustive-deps

  // Back from the editor: the Change LTS button, which has just come back, takes the focus.
  useEffect(() => {
    if (!editing && returnToButton.current) {
      returnToButton.current = false;
      changeButton.current?.focus();
    }
  }, [editing]);

  // Back from the junction's form: its button takes the focus.
  useEffect(() => {
    if (!suggestingJunction && returnToJunction.current) {
      returnToJunction.current = false;
      junctionButton.current?.focus();
    }
  }, [suggestingJunction]);

  // Back from the suggestion form: its button takes the focus.
  useEffect(() => {
    if (!suggesting && returnToSuggest.current) {
      returnToSuggest.current = false;
      suggestButton.current?.focus();
    }
  }, [suggesting]);

  // A signed-in rider (never the admin, who edits) reads their own suggestion's status for the road.
  const infoWay = state.kind === "ready" && state.info.found ? (state.info.osm_way_id ?? null) : null;
  const asksMine = me.signed_in && !me.can_change_lts;
  useEffect(() => {
    setMySuggestion(null);
    if (infoWay === null || !asksMine) return;
    const controller = new AbortController();
    void fetchMySuggestion(window.location.origin, infoWay, controller.signal).then((found) => {
      if (!controller.signal.aborted) setMySuggestion(found);
    });
    return () => controller.abort();
  }, [infoWay, asksMine, suggesting]);

  // Back from Mark closed: its button takes the focus.
  useEffect(() => {
    if (!closing && returnToClosing.current) {
      returnToClosing.current = false;
      closeButton.current?.focus();
    }
  }, [closing]);

  // Back from the hazard form: Mark a hazard takes the focus.
  useEffect(() => {
    if (!reporting && returnToHazard.current) {
      returnToHazard.current = false;
      hazardButton.current?.focus();
    }
  }, [reporting]);
  // The federal data and a Mass Ride's hazards can come after the road's answer (a Mass Ride's first
  // look): the status sentence is said again with them, so a screen reader hears it without reading on.
  const readyNow = state.kind === "ready" && state.info.found ? state.info : null;
  const hazardSaidNow = hazardSaid(hazardOnPiece(massRide ? hazards : null, readyNow));
  useEffect(() => {
    const again = refreshedSaid(request, stateFor.current, state, federalSaid, hazardSaidNow);
    if (again !== null) setSaid(again);
    // Only a change of the area's or the hazard's words: the answer's own arrival sets `said` above.
  }, [federalSaid, hazardSaidNow]); // eslint-disable-line react-hooks/exhaustive-deps

  // However it closes - Escape, the Close button, the backdrop - the focus goes back.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onDialogClose = () => {
      // A late `close` (queued after Escape) whose dialog has since reopened for a newer
      // request: that request, its focus and its fetch are not this event's to end.
      if (dialog.open) return;
      const back = returnTo.current;
      returnTo.current = null;
      setSaid("");
      onClose(shown.current);
      if (back instanceof HTMLElement && back.isConnected && back !== document.body && back !== document.documentElement) {
        back.focus();
        if (document.activeElement === back) return;
      }
      fallbackFocus?.()?.focus();
    };
    dialog.addEventListener("close", onDialogClose);
    return () => dialog.removeEventListener("close", onDialogClose);
  }, [onClose, fallbackFocus]);

  const close = () => dialogRef.current?.close();

  const closeEditor = () => {
    returnToButton.current = true;
    setEditing(false);
  };

  const closeSuggest = () => {
    returnToSuggest.current = true;
    setSuggesting(false);
  };

  const closeJunction = () => {
    returnToJunction.current = true;
    setSuggestingJunction(false);
  };

  const closeHazard = () => {
    returnToHazard.current = true;
    setReporting(false);
  };

  const closeClosing = () => {
    returnToClosing.current = true;
    setClosing(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (closesDialog(event.key)) {
      event.preventDefault();
      // Escape cancels the editor, not the whole panel.
      if (editing) closeEditor();
      else if (suggesting) closeSuggest();
      else if (reporting) closeHazard();
      else if (closing) closeClosing();
      else if (suggestingJunction) closeJunction();
      else close();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    // One stop a radio group (the named stretch's What to change), as the browser's Tab order has it.
    // Only what is shown: a link inside a closed fold (`details`, hidden by content-visibility, which
    // still lays out a box) takes no focus, so a stop on it would leave the focus where it was.
    const shown = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el === document.activeElement || isShown(el));
    const items = tabStops(shown as (HTMLElement & TabCandidate)[]);
    let active = document.activeElement as HTMLElement | null;
    const radio = active as (HTMLElement & TabCandidate) | null;
    if (radio?.type === "radio" && radio.name && !items.includes(radio)) {
      // An unchecked radio of a group with a checked one (the choice moved under the focus):
      // Tab goes on from the group's stop, as the browser's own order does.
      active = items.find((i) => (i as HTMLElement & TabCandidate).type === "radio" && (i as HTMLElement & TabCandidate).name === radio.name) ?? active;
    }
    const index = items.indexOf(active as HTMLElement);
    if (index < 0 && active && active !== dialogRef.current && dialogRef.current.contains(active) && items.length > 0) {
      // On something the dialog focuses but Tab does not visit (a heading): move to the next stop in
      // page order from there, wrapping at the ends, so the editor's heading leads to its first control.
      event.preventDefault();
      neighbour(items, active, event.shiftKey).focus();
      return;
    }
    const next = nextFocus(index, items.length, event.shiftKey);
    if (next >= 0) {
      event.preventDefault();
      items[next].focus();
    }
  };

  const ready = state.kind === "ready" && state.info.found ? state.info : null;
  const sections = ready ? shownSections(ready, massRide) : [];
  const summary = ready ? shownSummary(ready, massRide) : [];
  const links = station ? stationLinks(station, WMATA_SLUGS) : [];
  const where = request ? subtitle(state, request.origin) : "";
  const osmEdit = ready ? osmEditUrl(ready) : null;
  const more = moreLink(ready);
  const actions = spotActions(plan.count, plan.loop);
  const editableWay = ready && me.can_change_lts && ready.osm_way_id != null ? ready.osm_way_id : null;
  // A rider the settings allow may suggest a level (an instance admin changes it instead).
  const suggestWay =
    ready && me.can_suggest && editableWay === null && ready.osm_way_id != null && ready.tier != null ? ready.osm_way_id : null;
  // Anyone else gets the short form (v0.7.0; SuggestQuick.tsx): signed out, or the settings keep the
  // full form closed to them.
  const quickWay =
    meKnown && ready && !me.can_suggest && !me.can_change_lts && ready.osm_way_id != null && ready.tier != null
      ? ready.osm_way_id
      : null;
  const suggestRoad = suggestWay ?? quickWay;
  const suggestingNow = suggesting && suggestRoad !== null;
  // A Mass Ride's rider-marked hazard on this road (325), and whether this rider may mark one: a road
  // not marked Avoid (there the map shows only Avoid), by a rider the settings allow.
  const hazard = massRide ? hazardOnPiece(hazards, ready) : null;
  const hazardWay =
    massRide && ready && me.can_suggest && ready.osm_way_id != null && ready.tier != null && ready.tier !== 5 ? ready.osm_way_id : null;
  const reportingNow = reporting && hazardWay !== null;
  // A reviewer marks the road closed (v0.7.0 closures): an instance admin or a reviewer role.
  const closureWay = ready && me.can_review_closures && ready.osm_way_id != null ? ready.osm_way_id : null;
  const closingNow = closing && closureWay !== null;
  // A junction at the spot, for a rider who may suggest (an instance admin never suggests).
  const suggestJunction = me.can_suggest ? junction : null;
  const suggestingJunctionNow = suggestingJunction && suggestJunction !== null && !suggestingNow && !reportingNow && !closingNow;
  const suggestCount = [suggestJunction, suggestRoad, hazardWay].filter((way) => way !== null).length;
  const suggestItems = (
    <>
              {suggestJunction !== null && (
                <li>
                  <button
                    type="button"
                    className="road-info-button"
                    ref={junctionButton}
                    aria-describedby={id("junction-note")}
                    onClick={() => setSuggestingJunction(true)}
                  >
                    {JUNCTION_SUGGEST_TEXT}
                  </button>
                </li>
              )}
              {suggestRoad !== null && (
                <li>
                  <button type="button" className="road-info-button" ref={suggestButton} onClick={() => setSuggesting(true)}>
                    {SUGGEST_TEXT}
                  </button>
                </li>
              )}
              {hazardWay !== null && (
                <li>
                  <button type="button" className="road-info-button" ref={hazardButton} onClick={() => setReporting(true)}>
                    {HAZARD_REPORT_TEXT}
                  </button>
                </li>
              )}
    </>
  );

  return (
    <dialog
      ref={dialogRef}
      className="road-info"
      aria-labelledby={id("title")}
      aria-describedby={avoid ? `${id("avoid")} ${id("where")}` : id("where")}
      aria-busy={state.kind === "loading" ? true : undefined}
      onKeyDown={onKeyDown}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === dialogRef.current;
      }}
      onClick={(event) => {
        // A click on the backdrop (the dialog element itself) closes it, if it was pressed there too.
        const fromBackdrop = pressedBackdrop.current;
        pressedBackdrop.current = false;
        if (event.target === dialogRef.current && fromBackdrop) close();
      }}
    >
      <div className="road-info-body">
        {request && avoid && (
          <div className="road-info-avoid" id={id("avoid")}>
            <p className="road-info-avoid-heading">
              <span className="avoid-symbol" aria-hidden="true">
                {AVOID_SYMBOL}
              </span>{" "}
              <strong>{AVOID_CARD_HEADING}.</strong>
            </p>
            <p className="road-info-avoid-text">{avoidCardText(avoid)}</p>
          </div>
        )}
        <header>
          <h2 id={id("title")} ref={headingRef} tabIndex={-1}>
            {infoHeading(state)}
          </h2>
          <button type="button" className="secondary" onClick={close}>
            Close
          </button>
        </header>
        <p id={id("where")} className="road-info-kind">
          {where}
        </p>
        {/* Always in the dialog, empty at first: a region created holding its text is often not spoken. */}
        <p className="visually-hidden road-info-said" role="status">
          {said}
        </p>
        {request && (
          <ul className="road-info-place" aria-label="Use this spot">
            {actions.map((action) => (
              <li key={action.choice}>
                <button
                  type="button"
                  className="secondary"
                  aria-disabled={action.unavailable ? true : undefined}
                  aria-describedby={action.unavailable ? id(`why-${action.choice}`) : undefined}
                  onClick={() => {
                    if (action.unavailable) return;
                    onPlace(action.choice, request.point);
                    close();
                  }}
                >
                  {action.text}
                </button>
              </li>
            ))}
            {onSetHome && (
              <li>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    onSetHome(request.point);
                    close();
                  }}
                >
                  {SET_AS_HOME_TEXT}
                </button>
              </li>
            )}
          </ul>
        )}
        {request && actions.some((a) => a.unavailable) && (
          <p className="hint road-info-place-why">
            {actions
              .filter((a) => a.unavailable)
              .map((a, n) => (
                <span key={a.choice}>
                  {n > 0 && " "}
                  {/* Read too: without the button's name the same reason twice reads as a stutter (the a11y review's N1). */}
                  {a.text}: <span id={id(`why-${a.choice}`)}>{a.unavailable}</span>
                </span>
              ))}
          </p>
        )}
        {state.kind === "loading" && <p className="road-info-status">Looking up this road…</p>}
        {state.kind === "error" && <p className="road-info-status">{state.message}</p>}
        {state.kind === "ready" && !state.info.found && <p className="road-info-status">{NO_ROAD_HINT}</p>}
        {federal && (
          // In view whatever the road answer is: a spot in a park may have no road within reach.
          <p className="road-info-federal">
            <span className="road-info-label">Federal land:</span> {federalSaid}{" "}
            <span className="road-info-federal-note">{FEDERAL_ADVICE}</span>
          </p>
        )}
        {hazard && (
          // A Mass Ride's rider-marked hazard (325, 326): its level and reason in words, never the rail alone.
          <p className={`road-info-hazard road-info-hazard-${hazard.level}`}>
            <span className="road-info-label">Rider-marked hazard:</span> {hazardPanelText(hazard)}
          </p>
        )}
        {summary.length > 0 && (
          <ul className="road-info-summary" aria-label="Summary">
            {summary.map((row) => (
              <li key={row.id} className={`road-info-line road-info-line-${row.id}`}>
                <span className="road-info-label">{row.label}:</span>{" "}
                {valueParts(row.value).map((part, n) => (
                  <span key={n}>
                    {n > 0 && (
                      <>
                        <span aria-hidden="true"> · </span>
                        <span className="visually-hidden">, </span>
                      </>
                    )}
                    {part}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        )}
        {mySuggestion && mySuggestion.osm_way_id === ready?.osm_way_id && (
          <p className="road-info-mine">
            <span className="road-info-label">Your suggestion:</span> {mySuggestionText(mySuggestion)}
          </p>
        )}
        {ready && request && (
          <StreetPhotoView title={ready.title} point={streetViewPoint(ready, request.point)} wayId={ready.osm_way_id} />
        )}
        {more && (
          // A mountain-bike trail's MORE page: trailheads, trail info and the day's conditions (slice 6).
          <p className="road-info-more">
            <a href={more.url} target="_blank" rel="noopener noreferrer">
              {more.label}
              <span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          </p>
        )}
        {climb && onShowClimb && (
          <div className="road-info-climb">
            <p id={id("climb")}>
              <span className="road-info-label">Climb here:</span> {climbLabel(climb)}{climb.name ? `, on ${climb.name}` : ""}
            </p>
            <button
              type="button"
              className="secondary"
              aria-describedby={id("climb")}
              onClick={() => {
                close();
                onShowClimb(climb);
              }}
            >
              {CLIMB_DETAILS_TEXT}
            </button>
          </div>
        )}
        {station && links.length > 0 && (
          <div className="road-info-stations">
            {/* The station's name in view, beside its short links (OWNER-DECISIONS 441q; the a11y review's N2). */}
            <p className="road-info-station-name" id={id("station")}>
              <span className="road-info-label">Nearby station:</span> {station.name}
            </p>
            <ul className="road-info-links" aria-labelledby={id("station")}>
              {links.map((link) => (
                <li key={link.href}>
                  <a href={link.href} target="_blank" rel="noopener noreferrer" aria-label={link.label}>
                    {link.text}
                  </a>
                </li>
              ))}
            </ul>
            <StationTimesList station={station} rail={rail} closed={Boolean(stationClosed?.(station))} />
          </div>
        )}
        {ready && (
          <details
            key={`${request?.point[0]},${request?.point[1]}`}
            className="road-info-details"
            open={summary.length === 0 ? true : undefined}
          >
            <summary>{DETAILS_TEXT}</summary>
            {sections.map((section) => (
              <section key={section.id} className={`road-info-section road-info-${section.id}`} aria-labelledby={id(section.id)}>
                <h3 id={id(section.id)}>{section.heading}</h3>
                <dl>
                  {section.rows.map((row) => (
                    <div key={row.label} className="road-info-row">
                      <dt>{row.label}</dt>
                      <dd>
                        {row.value}
                        {row.source && <span className="road-info-source">Source: {row.source}</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
            {wayRows(ready).length > 0 && (
              <section className="road-info-section road-info-way" aria-labelledby={id("way")}>
                <h3 id={id("way")}>The way in the map data</h3>
                <dl>
                  {wayRows(ready).map((row) => (
                    <div key={row.label} className="road-info-row">
                      <dt>{row.label}</dt>
                      <dd>{row.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            <p className="hint road-info-credit">
              Data: {ready.attribution.join(", ")} and the sources above; traffic stress by RouteMaker's classifier and
              the owner's ratings.
            </p>
            {/* OWNER-DECISIONS 461: the rider-facing page on how ratings work, in the same tab. */}
            <StressPageLink className="road-info-how" />
          </details>
        )}
        {ready && (
          <p className="hint road-info-credit-short">
            Data: {ready.attribution.join(", ")} and others (see {DETAILS_TEXT}).
          </p>
        )}
        {request && editing && editableWay !== null && ready && (
          <div className="road-info-actions">
            <StressEditor
              origin={window.location.origin}
              wayId={editableWay}
              title={ready.title}
              onClose={closeEditor}
              onChanged={(generation) => {
                setReload((n) => n + 1);
                onStressChanged?.(generation);
              }}
            />
          </div>
        )}
        {request && suggestingNow && ready && quickWay !== null && (
          <div className="road-info-actions">
            <SuggestQuick
              origin={window.location.origin}
              wayId={quickWay}
              title={ready.title}
              current={ready.step ?? ready.tier ?? 3}
              point={streetViewPoint(ready, request.point)}
              halfSteps={ready.half_steps === true}
              onClose={closeSuggest}
            />
          </div>
        )}
        {request && suggestingNow && ready && suggestWay !== null && (
          <div className="road-info-actions">
            <SuggestChange
              origin={window.location.origin}
              wayId={suggestWay}
              title={ready.title}
              current={ready.step ?? ready.tier ?? 3}
              point={streetViewPoint(ready, request.point)}
              halfSteps={ready.half_steps === true}
              onClose={closeSuggest}
            />
          </div>
        )}
        {request && reportingNow && ready && hazardWay !== null && (
          <div className="road-info-actions">
            <HazardReport
              origin={window.location.origin}
              wayId={hazardWay}
              title={ready.title}
              point={streetViewPoint(ready, request.point)}
              current={hazard}
              onClose={closeHazard}
            />
          </div>
        )}
        {request && closingNow && ready && closureWay !== null && (
          <div className="road-info-actions">
            <ClosureEntry origin={window.location.origin} wayId={closureWay} title={ready.title} onClose={closeClosing} />
          </div>
        )}
        {request && suggestingJunctionNow && suggestJunction !== null && (
          <div className="road-info-actions">
            <SuggestJunction origin={window.location.origin} junction={suggestJunction} shown={junctionShown} onClose={closeJunction} />
          </div>
        )}
        {request && !(editing && editableWay !== null) && !suggestingNow && !reportingNow && !closingNow && !suggestingJunctionNow && (
          <div className="road-info-actions">
            <ul className="road-info-buttons" aria-label="Actions">
              <li>
                <a
                  className="road-info-button"
                  href={streetViewUrl(streetViewPoint(ready, request.point))}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-describedby={id("sv-note")}
                >
                  {STREET_VIEW_TEXT}
                </a>
              </li>
              {osmEdit && (
                <li>
                  <a
                    className="road-info-button"
                    href={osmEdit}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-describedby={id("osm-note")}
                  >
                    {OSM_EDIT_TEXT}
                  </a>
                </li>
              )}
              {editableWay !== null && (
                <li>
                  <button type="button" className="road-info-button" ref={changeButton} onClick={() => setEditing(true)}>
                    {CHANGE_LTS_TEXT}
                  </button>
                </li>
              )}
              {closureWay !== null && (
                <li>
                  <button type="button" className="road-info-button" ref={closeButton} onClick={() => setClosing(true)}>
                    {MARK_CLOSED_TEXT}
                  </button>
                </li>
              )}
              {suggestCount >= 2 && (
                <li>
                  <button
                    type="button"
                    className="road-info-button suggest-menu"
                    aria-expanded={suggestMenu}
                    aria-controls={suggestMenuId}
                    onClick={() => setSuggestMenu(!suggestMenu)}
                  >
                    {SUGGEST_MENU_TEXT}
                  </button>
                </li>
              )}
              {suggestCount < 2 && suggestItems}
            </ul>
            {suggestCount >= 2 && (
              <ul id={suggestMenuId} className="road-info-buttons road-info-suggest" aria-label="Suggest a change" hidden={!suggestMenu}>
                {suggestItems}
              </ul>
            )}
            <p className="hint road-info-notes">
              <span aria-hidden="true">{STREET_VIEW_TEXT}: </span>
              <span id={id("sv-note")}>{STREET_VIEW_NOTE}</span>
              {osmEdit && (
                <>
                  {" "}
                  <span aria-hidden="true">{OSM_EDIT_TEXT}: </span>
                  <span id={id("osm-note")}>{OSM_EDIT_NOTE}</span>
                </>
              )}
              {suggestJunction !== null && (
                <>
                  {" "}
                  <span aria-hidden="true">{JUNCTION_SUGGEST_TEXT}: </span>
                  <span id={id("junction-note")}>{junctionNote(suggestJunction.name)}</span>
                </>
              )}
            </p>
          </div>
        )}
      </div>
    </dialog>
  );
}
