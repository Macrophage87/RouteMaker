/**
 * The map's road panel (OWNER-DECISIONS 441, 441a; lib/roadInfo.ts): what RouteMaker
 * knows of the road or path nearest a spot, with a bottom row of links drawn as
 * buttons: Street View, Edit in OSM, and, for an instance admin, Change LTS (OWNER-DECISIONS 441g, 441h,
 * 441m), which opens the stress editor (StressEditor.tsx) in this same dialog in place of the row.
 *
 * Compact, so the common case fits a phone without scrolling: the name, its kind, a
 * short summary list (one line a fact, read in order), a nearby station's pages, a
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
import { stationLinks } from "./lib/stationLinks.ts";
import { WMATA_SLUGS } from "./lib/railData.ts";
import type { Station } from "./lib/railStations.ts";
import { StressPageLink } from "./lib/stressLegend.ts";
import { closesDialog, nextFocus } from "./lib/rideTypeDialog.ts";
import { CHANGE_LTS_TEXT, NO_ME, fetchMe, type Me } from "./lib/stressEditor.ts";
import { StressEditor } from "./StressEditor.tsx";

interface Props {
  /** The spot asked about, or null while the panel is closed. */
  request: InfoRequest | null;
  /** The Mass Ride map is showing: its capacity section shows too. */
  massRide: boolean;
  /** A station near the spot whose pages the panel offers, or null. */
  station: Station | null;
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
}

const FOCUSABLE =
  "button:not([disabled]), [href], summary, input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

/** The stop after (or before) `from` in page order among `items`, wrapping round at the ends. */
function neighbour(items: HTMLElement[], from: HTMLElement, backwards: boolean): HTMLElement {
  if (backwards) {
    const before = items.filter((i) => from.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_PRECEDING);
    return before.length ? before[before.length - 1] : items[items.length - 1];
  }
  const after = items.filter((i) => from.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING);
  return after.length ? after[0] : items[0];
}

export function RoadInfoDialog({ request, massRide, station, onClose, fallbackFocus, onStressChanged, plan, onPlace }: Props) {
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
  const [editing, setEditing] = useState(false);
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
    setState({ kind: "loading" });
    setSaid("");
    setEditing(false);
    setReload(0);
    void fetchMe(window.location.origin).then(setMe);
    const controller = new AbortController();
    fetchSegmentInfo(window.location.origin, request.point, controller.signal).then(
      (next) => {
        setState(next);
        setSaid(infoSaid(next));
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

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (closesDialog(event.key)) {
      event.preventDefault();
      // Escape cancels the editor, not the whole panel.
      if (editing) closeEditor();
      else close();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const active = document.activeElement as HTMLElement | null;
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
  const actions = spotActions(plan.count, plan.loop);
  const editableWay = ready && me.can_change_lts && ready.osm_way_id != null ? ready.osm_way_id : null;

  return (
    <dialog
      ref={dialogRef}
      className="road-info"
      aria-labelledby={id("title")}
      aria-describedby={id("where")}
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
        {request && !(editing && editableWay !== null) && (
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
            </ul>
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
            </p>
          </div>
        )}
      </div>
    </dialog>
  );
}
