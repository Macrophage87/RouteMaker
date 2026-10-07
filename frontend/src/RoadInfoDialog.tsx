/**
 * The map's road panel (OWNER-DECISIONS 441, 441a; lib/roadInfo.ts): what RouteMaker
 * knows of the road or path nearest a spot, each figure with its source in words, and
 * the "Open Street View here" link.
 *
 * The platform's own modal `<dialog>`, as the ride-type picker is: it makes the rest of
 * the page inert while open, Escape closes it, and Tab is held inside it. On open the
 * focus goes to its heading, so a screen reader says what it is about first; on close
 * it goes back to whatever opened it (the map, or the Road info button). Each part is a
 * labelled section with a heading, the figures a description list; nothing depends on
 * colour. The answer is also said, briefly, through the page's live region (App's
 * `announce`), so a rider who stays on the heading hears it come in.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  NO_ROAD_HINT,
  STREET_VIEW_NOTE,
  STREET_VIEW_TEXT,
  fetchSegmentInfo,
  infoHeading,
  infoSaid,
  originText,
  shownSections,
  streetViewUrl,
  type InfoRequest,
  type InfoState,
} from "./lib/roadInfo.ts";
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
}

const FOCUSABLE = "button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";

export function RoadInfoDialog({ request, massRide, station, onClose, announce }: Props) {
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

  const sections = state.kind === "ready" && state.info.found ? shownSections(state.info, massRide) : [];
  const links = station ? stationLinks(station, WMATA_SLUGS) : [];

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
        <p id={id("where")} className="hint">
          {request ? originText(request.origin) : ""}
        </p>
        {state.kind === "loading" && <p className="road-info-status">Looking up what is known about this road…</p>}
        {state.kind === "error" && <p className="road-info-status">{state.message}</p>}
        {state.kind === "ready" && !state.info.found && <p className="road-info-status">{NO_ROAD_HINT}</p>}
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
        {station && links.length > 0 && (
          <section className="road-info-section road-info-station" aria-labelledby={id("station")}>
            <h3 id={id("station")}>Nearby station: {station.name}</h3>
            <ul className="station-links">
              {links.map((link) => (
                <li key={link.href}>
                  <a href={link.href} target="_blank" rel="noopener noreferrer" aria-describedby={id("station-note")}>
                    {link.text}
                  </a>
                </li>
              ))}
            </ul>
            <p id={id("station-note")} className="hint">
              {STATION_LINK_NOTE}
            </p>
          </section>
        )}
        {request && (
          <section className="road-info-section road-info-streetview" aria-labelledby={id("streetview")}>
            <h3 id={id("streetview")}>Street View</h3>
            <p>
              <a
                href={streetViewUrl(request.point)}
                target="_blank"
                rel="noopener noreferrer"
                aria-describedby={id("streetview-note")}
              >
                {STREET_VIEW_TEXT}
              </a>
            </p>
            <p id={id("streetview-note")} className="hint">
              {STREET_VIEW_NOTE}
            </p>
          </section>
        )}
        {state.kind === "ready" && state.info.found && (
          <p className="hint road-info-credit">
            Data: {state.info.attribution.join(", ")}; traffic stress by RouteMaker's classifier and the owner's ratings.
          </p>
        )}
      </div>
    </dialog>
  );
}
