/**
 * Go's card for a spot tapped on the map (Stephen, 2026-10-28: "For routing, on a click instead of showing the road,
 * show the address and what's near"; then "Let them show all on the map so you can select them" and "Maybe just show
 * that in most cases. For restaurants and the like, label them"; the mockup shown to him, ui-audit
 * go-tap-nearby-mockup.png): the big Route here on top, the spot's address under it, the area and how far it is,
 * then one line, "5 places nearby, shown on the map", with a List button. The places themselves are pins on the map,
 * a named one labelled with its name (app/spotPins.ts; lib/spotNearby.ts); a pin opens the place's own card
 * (lib/stopCard.ts), never a route by itself. List shows the same places as buttons, for a screen reader and the
 * keyboard, with Road info under them (the road card, as the tap opened before; a long press still opens it too).
 *
 * Placed as the road card is (dialog.road-info: a sheet from the bottom on a phone), but not modal: the map above it
 * stays live, so its pins can be pressed and another tap moves the card to that spot. Escape and Close close it; the
 * focus goes to Route here on open and back to the map on close. The dialog is named by the address.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { formatDistance } from "./lib/format.ts";
import type { LonLat } from "./lib/geo.ts";
import type { GeoResult } from "./lib/geocode.ts";
import { Icon } from "./Icon.tsx";
import { ROUTE_HERE_TEXT } from "./lib/roadInfo.ts";
import { closesDialog } from "./lib/rideTypeDialog.ts";
import {
  FINDING_ADDRESS,
  NEARBY_HEADING,
  NEARBY_LOADING,
  NOTHING_NEAR,
  ROAD_INFO_TEXT,
  SPOT_LIST_TEXT,
  spotAddress,
  spotAwayText,
  spotCountLine,
  spotRowName,
  type SpotAddress,
  type SpotRow,
} from "./lib/spotNearby.ts";
import { t } from "./lib/i18n.ts";

/** The spot asked about: a new object per tap, so a second tap on the same spot opens the card again. */
export interface SpotRequest {
  point: LonLat;
}

interface Props {
  /** The tapped spot, or null while the card is closed. */
  request: SpotRequest | null;
  /** The reverse geocoder, through the page's one gate (lib/geocode.ts nameSender). */
  lookup: (point: LonLat) => Promise<GeoResult>;
  /** A name the page already has for the spot, used if the look-up fails. */
  fallbackName?: (point: LonLat) => string | undefined;
  /** Where the rider is, if known: the card says how far the spot is. */
  here?: LonLat | null;
  /** The nearby places, nearest first; null while the map's places load. */
  rows: readonly SpotRow[] | null;
  onRouteHere: (point: LonLat) => void;
  /** A row of the list pressed: its index (its pin on the map does the same). */
  onPick: (index: number) => void;
  onRoadInfo: (point: LonLat) => void;
  onClose: () => void;
  /** Where the focus goes on close when nothing else can take it: the map. */
  fallbackFocus?: () => HTMLElement | null;
}

export function GoSpotDialog({ request, lookup, fallbackName, here = null, rows, onRouteHere, onPick, onRoadInfo, onClose, fallbackFocus }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const routeRef = useRef<HTMLButtonElement>(null);
  const [address, setAddress] = useState<SpotAddress | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const base = useId();
  const titleId = `${base}-title`;
  const listId = `${base}-nearby`;
  const lookupRef = useRef(lookup);
  lookupRef.current = lookup;
  const fallbackRef = useRef(fallbackName);
  fallbackRef.current = fallbackName;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!request) {
      if (dialog.open) dialog.close();
      return;
    }
    // Not modal: the map's pins stay pressable while the card is open.
    if (!dialog.open) dialog.show();
    routeRef.current?.focus();
    setAddress(null);
    setListOpen(false);
    let live = true;
    const fallback = () => fallbackRef.current?.(request.point);
    lookupRef.current(request.point).then(
      (result) => {
        if (live) setAddress(spotAddress(result, fallback()));
      },
      () => {
        if (live) setAddress(spotAddress(null, fallback()));
      },
    );
    return () => {
      live = false;
    };
  }, [request]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onDialogClose = () => {
      if (dialog.open) return;
      onClose();
      // Back to the map, unless the press that closed it put the focus somewhere of its own (the road card).
      const lost = document.activeElement === document.body || !document.activeElement?.isConnected || dialog.contains(document.activeElement);
      if (lost) fallbackFocus?.()?.focus();
    };
    dialog.addEventListener("close", onDialogClose);
    return () => dialog.removeEventListener("close", onDialogClose);
  }, [onClose, fallbackFocus]);

  const close = () => dialogRef.current?.close();
  const openRoad = (point: LonLat) => {
    close();
    onRoadInfo(point);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (closesDialog(event.key)) {
      event.preventDefault();
      close();
    }
  };
  const away = request ? spotAwayText(request.point, here) : "";
  const area = address?.area ?? "";
  const count = rows === null ? NEARBY_LOADING : rows.length === 0 ? NOTHING_NEAR : spotCountLine(rows.length);

  return (
    <dialog ref={dialogRef} className="road-info go-spot" aria-labelledby={titleId} aria-busy={address === null ? true : undefined} onKeyDown={onKeyDown}>
      <div className="road-info-body">
        <div className="go-spot-top">
          <button type="button" className="secondary go-spot-close" aria-label={t("Close")} title={t("Close")} onClick={close}>
            <Icon name="x" size={22} />
          </button>
        </div>
        {request && (
          <button
            type="button"
            ref={routeRef}
            className="road-info-route-here"
            onClick={() => {
              onRouteHere(request.point);
              close();
            }}
          >
            {ROUTE_HERE_TEXT}
          </button>
        )}
        <h2 id={titleId} className="go-spot-heading">
          {address ? address.heading : FINDING_ADDRESS}
        </h2>
        {(area || away) && (
          <p className="road-info-kind go-spot-sub">
            {area}
            {area && away && (
              <>
                <span aria-hidden="true"> · </span>
                <span className="visually-hidden">, </span>
              </>
            )}
            {away}
          </p>
        )}
        <div className="go-spot-foot">
          <p className="go-spot-count">{count}</p>
          {rows !== null && rows.length > 0 && (
            <button type="button" className="secondary go-spot-list-button" aria-expanded={listOpen} aria-controls={listId} onClick={() => setListOpen((open) => !open)}>
              {SPOT_LIST_TEXT}
            </button>
          )}
          {/* With no list to hold it, Road info stands here. */}
          {request && rows !== null && rows.length === 0 && (
            <button type="button" className="secondary go-spot-road" onClick={() => openRoad(request.point)}>
              {ROAD_INFO_TEXT}
            </button>
          )}
        </div>
        <div id={listId} className="go-spot-list" hidden={!listOpen || rows === null || rows.length === 0}>
          <h3 id={`${listId}-heading`} className="visually-hidden">
            {NEARBY_HEADING}
          </h3>
          {/* role="list": WebKit drops a list's role once its bullets are styled away. */}
          <ul className="go-spot-nearby" role="list" aria-labelledby={`${listId}-heading`}>
            {(rows ?? []).map((row, index) => (
              <li key={row.id}>
                <button type="button" className="go-spot-row" aria-label={spotRowName(row)} onClick={() => onPick(index)}>
                  <span className="go-spot-row-text" aria-hidden="true">
                    <strong>{row.name}</strong>
                    {row.kindText && <span className="go-spot-row-kind"> · {row.kindText}</span>}
                  </span>
                  <span className="go-spot-row-far" aria-hidden="true">
                    {formatDistance(row.metres)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {request && (
            <button type="button" className="secondary go-spot-road" onClick={() => openRoad(request.point)}>
              {ROAD_INFO_TEXT}
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
