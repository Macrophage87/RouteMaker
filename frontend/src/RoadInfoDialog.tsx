/**
 * The map's road panel (OWNER-DECISIONS 441, 441a; lib/roadInfo.ts): what RouteMaker
 * knows of the road or path nearest a spot, with a bottom row of links drawn as
 * buttons: Street View, Edit in OSM, and (when the editing release passes it) Change LTS.
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
 * sentence, through the page's live region (App's `announce`), so a rider who stays on
 * the heading hears it come in.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  DETAILS_TEXT,
  NO_ROAD_HINT,
  OSM_EDIT_NOTE,
  OSM_EDIT_TEXT,
  spotActions,
  STREET_VIEW_NOTE,
  STREET_VIEW_TEXT,
  fetchSegmentInfo,
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
  type SegmentInfo,
} from "./lib/roadInfo.ts";
import type { PlaceChoice } from "./lib/geocode.ts";
import { STATION_LINK_NOTE, stationLinks } from "./lib/stationLinks.ts";
import { WMATA_SLUGS } from "./lib/railData.ts";
import type { Station } from "./lib/railStations.ts";
import { closesDialog, nextFocus } from "./lib/rideTypeDialog.ts";

interface Props {
  /** The spot asked about, or null while the panel is closed. */
  request: InfoRequest | null;
  /** The Mass Ride map is showing: its capacity section shows too. */
  massRide: boolean;
  /** A station near the spot whose pages the panel offers, or null. */
  station: Station | null;
  onClose: () => void;
  /** Say a short sentence through the page's live region. */
  announce: (text: string) => void;
  /**
   * The editing release's hook (OWNER-DECISIONS 441g/441h, 441m): the "Change LTS" control
   * for a signed-in instance admin, drawn third in the bottom action row. Not passed until
   * the editor exists, so nothing shows now; it returns null for anyone who may not edit.
   */
  changeLtsAction?: (info: SegmentInfo) => ReactNode | null;
  /** The plan's point count and whether it is a loop, for the top row (OWNER-DECISIONS 441n). */
  plan: { count: number; loop: boolean };
  /** Put the spot in the plan as its start, its end or a stop; the panel then closes. */
  onPlace: (choice: PlaceChoice, point: [number, number]) => void;
}

const FOCUSABLE = "button:not([disabled]), [href], summary, [tabindex]:not([tabindex='-1'])";

export function RoadInfoDialog({ request, massRide, station, onClose, announce, changeLtsAction, plan, onPlace }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnTo = useRef<Element | null>(null);
  const [state, setState] = useState<InfoState>({ kind: "loading" });
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
      dialog.showModal?.();
    }
    headingRef.current?.focus();
    setState({ kind: "loading" });
    const controller = new AbortController();
    fetchSegmentInfo(window.location.origin, request.point, controller.signal).then(
      (next) => {
        setState(next);
        announce(infoSaid(next));
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [request?.point[0], request?.point[1], request?.origin]);

  // However it closes - Escape, the Close button, the backdrop - the focus goes back.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onDialogClose = () => {
      const back = returnTo.current;
      returnTo.current = null;
      onClose();
      if (back instanceof HTMLElement && back.isConnected && back !== document.body) back.focus();
    };
    dialog.addEventListener("close", onDialogClose);
    return () => dialog.removeEventListener("close", onDialogClose);
  }, [onClose]);

  const close = () => dialogRef.current?.close();

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (closesDialog(event.key)) {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const index = items.indexOf(document.activeElement as HTMLElement);
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
  const changeLts = ready && changeLtsAction ? changeLtsAction(ready) : null;

  return (
    <dialog
      ref={dialogRef}
      className="road-info"
      aria-labelledby={id("title")}
      aria-describedby={id("where")}
      aria-busy={state.kind === "loading" ? true : undefined}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        if (event.target === dialogRef.current) close();
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
                  <span aria-hidden="true">{a.text}: </span>
                  <span id={id(`why-${a.choice}`)}>{a.unavailable}</span>
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
          <ul className="road-info-links road-info-stations" aria-label={`Nearby station: ${station.name}`}>
            {links.map((link) => (
              <li key={link.href}>
                <a href={link.href} target="_blank" rel="noopener noreferrer" aria-describedby={id("station-note")}>
                  {link.text}
                </a>
              </li>
            ))}
          </ul>
        )}
        {station && links.length > 0 && (
          <p className="visually-hidden" id={id("station-note")}>
            {STATION_LINK_NOTE}
          </p>
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
          </details>
        )}
        {ready && (
          <p className="hint road-info-credit-short">
            Data: {ready.attribution.join(", ")} and others (see {DETAILS_TEXT}).
          </p>
        )}
        {request && (
          <div className="road-info-actions">
            <ul className="road-info-buttons" aria-label="Actions">
              <li>
                <a
                  className="road-info-button"
                  href={streetViewUrl(request.point)}
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
              {changeLts && <li>{changeLts}</li>}
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
