/**
 * Go (UI-CLEANUP, the owner's commute view; lib/appMode.ts): the phone's few-steps view, as the approved
 * mockup of 2026-10-11 draws it. Over the map, a top bar (Menu, the Go/Plan switch, Layers, Locate); at the
 * bottom, a sheet with one Where to? box, four place chips (Home, Food, Water, Restroom: the owner's
 * choice 3), the commute ride types (choice 10), and once a route is shown its time, stress bar, one alert
 * and Start. Every other control is in the Menu, the Ride sheet or Plan, two presses away at most.
 *
 * Plan keeps the full panel; its map has Food and Water chips (PlanMapChips), where Go has place chips.
 */
import { useId, useState, type ReactNode } from "react";
import { Icon } from "../Icon.tsx";
import { PlaceSearch } from "../PlaceSearch.tsx";
import type { LonLat } from "../lib/geo.ts";
import type { GeoGate, Place, PlaceChoice } from "../lib/geocode.ts";
import { MODE_LABEL, MODE_SWITCH_HINT, MODE_SWITCH_NAME, type AppMode } from "../lib/appMode.ts";
import { HOME_NOT_SET, HOME_SIGN_IN } from "../lib/myGo.ts";
import { BEST_ORDER_LABEL } from "../lib/stopOrder.ts";

export type GoSheetSize = "peek" | "half" | "full";

/** The handle's next size: peek, half, full, then back to peek. */
export function nextSheetSize(size: GoSheetSize): GoSheetSize {
  return size === "peek" ? "half" : size === "half" ? "full" : "peek";
}

const SIZE_SAID: Record<GoSheetSize, string> = { peek: "small", half: "half height", full: "full height" };

/** Go or Plan: two toggle buttons, the pressed one the view in use (the owner's choice 1: either view can switch). */
export function ModeSwitch({ mode, onChange, className = "" }: { mode: AppMode; onChange: (next: AppMode) => void; className?: string }) {
  const hintId = useId();
  return (
    <div className={`mode-switch ${className}`.trim()} role="group" aria-label={MODE_SWITCH_NAME} aria-describedby={hintId}>
      {(["go", "plan"] as const).map((m) => (
        <button key={m} type="button" className="mode-button" aria-pressed={mode === m} onClick={() => onChange(m)}>
          {MODE_LABEL[m]}
        </button>
      ))}
      <span id={hintId} hidden>
        {MODE_SWITCH_HINT}
      </span>
    </div>
  );
}

/** Go's bar over the map: Menu, the switch, Layers and Locate, and the destination once there is one. */
export function GoTopBar({
  mode,
  onMode,
  onMenu,
  onLayers,
  onLocate,
  locating,
  destination,
  onClear,
}: {
  mode: AppMode;
  onMode: (next: AppMode) => void;
  onMenu: (button: HTMLButtonElement) => void;
  onLayers: (button: HTMLButtonElement) => void;
  onLocate: () => void;
  locating: boolean;
  /** The route's destination's name, or null before there is a route. */
  destination: string | null;
  onClear: () => void;
}) {
  return (
    <nav className="go-top" aria-label="Go">
      <div className="go-top-row">
        <button type="button" className="icon-button go-menu" onClick={(event) => onMenu(event.currentTarget)}>
          <Icon name="menu" />
          <span className="icon-button-label">Menu</span>
        </button>
        <ModeSwitch mode={mode} onChange={onMode} />
        <span className="go-top-end">
          <button type="button" className="icon-button go-layers" onClick={(event) => onLayers(event.currentTarget)}>
            <Icon name="layers" />
            <span className="icon-button-label">Layers</span>
          </button>
          <button type="button" className="icon-button go-locate" onClick={onLocate} aria-disabled={locating || undefined}>
            <Icon name="locate" />
            <span className="icon-button-label">{locating ? "Locating…" : "Locate"}</span>
          </button>
        </span>
      </div>
      {destination !== null && (
        <div className="go-destination">
          <Icon name="pin" size={18} />
          <span className="go-destination-name">
            <span className="visually-hidden">To </span>
            {destination}
          </span>
          <button type="button" className="go-clear" onClick={onClear} aria-label={`Clear the route to ${destination}`}>
            <Icon name="x" size={18} />
          </button>
        </div>
      )}
    </nav>
  );
}

export interface GoPlaces {
  /** Signed in with a Home: the chip rides there. Else it opens My Go (and says why). */
  homeReady: boolean;
  signedIn: boolean;
  onHome: (chip: HTMLButtonElement) => void;
  onFood: (chip: HTMLButtonElement) => void;
  onWater: (chip: HTMLButtonElement) => void;
  onRestroom: (chip: HTMLButtonElement) => void;
}

/**
 * Go's "Add a stop" (v0.7.0, "Keep adding stops by search"): one field in the route sheet, above the route; a
 * place picked is a stop where it adds the least distance, routed at once (Undo removes it). Best order sits
 * beside it with two or more stops; it is the field's only company, so Go stays one control per feature.
 */
export function GoAddStop({
  geoGate,
  searchBias,
  onPick,
  full,
  orderShown,
  ordering,
  onBestOrder,
}: {
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
  onPick: (place: Place) => void;
  full: boolean;
  orderShown: boolean;
  ordering: boolean;
  onBestOrder: () => void;
}) {
  return (
    <div className="go-add-stop">
      <PlaceSearch variant="stop" pointCount={2} full={full} gate={geoGate} bias={searchBias} onPick={(place: Place) => onPick(place)} />
      {orderShown && (
        <button type="button" className="secondary" onClick={onBestOrder} aria-disabled={ordering ? true : undefined}>
          {BEST_ORDER_LABEL}
        </button>
      )}
    </div>
  );
}

/** Go's sheet: the handle, Where to?, the place chips, the ride types, the notice and the route. */
export function GoSheet({
  size,
  onSize,
  pointCount,
  geoGate,
  searchBias,
  onPick,
  onTopPlace,
  places,
  rides,
  notice,
  route,
  addStop = null,
  startLine,
  startMissing,
  onStartPick,
}: {
  /** Go's "Add a stop" with a route (GoAddStop), or null: before a route, and during a ride. */
  addStop?: ReactNode;
  size: GoSheetSize;
  onSize: (next: GoSheetSize) => void;
  pointCount: number;
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
  onPick: (place: Place) => void;
  /** The top result of Where to? while the rider looks at it: Go starts routing there early (v0.7.0, "Faster routing"). */
  onTopPlace?: (place: Place) => void;
  places: GoPlaces;
  /** The ride type chips (RideChips). */
  rides: ReactNode;
  notice: string | null;
  /** The Route section, Go's variant, or null before there are points. */
  route: ReactNode;
  /** Go's start line ("Start: your current location"; lib/appMode.ts goStartLine). */
  startLine: string;
  /** No start and no location: the start box is shown open. */
  startMissing: boolean;
  /** A start typed in: it replaces the location. */
  onStartPick: (place: Place) => void;
}) {
  const homeHint = useId();
  const startBoxId = useId();
  const [startOpen, setStartOpen] = useState(false);
  const startShown = startOpen || startMissing;
  const next = nextSheetSize(size);
  const routeShown = route !== null;
  return (
    <div className={`go-sheet go-${size}`}>
      <button type="button" className="go-handle" onClick={() => onSize(next)} aria-label={`Sheet: ${SIZE_SAID[size]}. Make it ${SIZE_SAID[next]}`}>
        <span className="go-handle-bar" aria-hidden="true" />
      </button>
      {/* Where to? stays first while there is no route; with one, the route comes first (it is what the rider is
          looking at), and Where to? follows for a new place. */}
      {routeShown && addStop && size !== "peek" && addStop}
      {routeShown && route}
      <div className="go-where" hidden={routeShown && size === "peek"}>
        {/* The start (the owner, 2026-10-11): the rider's location by default; a typed start replaces it (a press on the map is the destination). */}
        {!routeShown && (
          <div className="go-start-row">
            <p className="go-start-line">
              <Icon name="locate" size={18} />
              <span>{startLine}</span>
            </p>
            {!startMissing && (
              <button type="button" className="link go-change-start" aria-expanded={startOpen} aria-controls={startBoxId} onClick={() => setStartOpen(!startOpen)}>
                Change start
              </button>
            )}
          </div>
        )}
        {!routeShown && (
          <div id={startBoxId} className="go-start-search" hidden={!startShown}>
            <PlaceSearch
              variant="start"
              pointCount={0}
              full={false}
              gate={geoGate}
              bias={searchBias}
              onPick={(place: Place, _choice: PlaceChoice) => {
                setStartOpen(false);
                onStartPick(place);
              }}
            />
          </div>
        )}
        <PlaceSearch variant="go" pointCount={pointCount} full={false} gate={geoGate} bias={searchBias} onPick={(place: Place, _choice: PlaceChoice) => onPick(place)} onTopPlace={onTopPlace} />
        <div className="chip-row go-places" role="group" aria-label="Places">
          <button
            type="button"
            className="chip place-chip"
            onClick={(event) => places.onHome(event.currentTarget)}
            aria-describedby={places.homeReady ? undefined : homeHint}
          >
            <Icon name="home" size={18} />
            Home
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onFood(event.currentTarget)}>
            <Icon name="food" size={18} />
            Food
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onWater(event.currentTarget)}>
            <Icon name="water" size={18} />
            Water
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onRestroom(event.currentTarget)}>
            <Icon name="wc" size={18} />
            Restroom
          </button>
        </div>
        {!places.homeReady && (
          <p id={homeHint} className="hint go-home-hint">
            {places.signedIn ? HOME_NOT_SET : HOME_SIGN_IN}
          </p>
        )}
        {!routeShown && rides}
      </div>
      {/* With a route, the ride types follow it (bigger than peek): one press re-plans, and Bikeshare names
          its pick-up and drop-off stations in the route's Bikeshare plan (only in Bikeshare: the owner's word). */}
      {routeShown && size !== "peek" && <div className="go-route-rides">{rides}</div>}
      {/* Said by the app's own region (Go has no Points section's status line; App noticeSaidElsewhere). */}
      {notice && <p className="go-notice notice">{notice}</p>}
    </div>
  );
}

/** Plan's map chips (the mockup's Plan view): Food and Water open their sheets in the panel. */
export function PlanMapChips({ onFood, onWater }: { onFood: (chip: HTMLButtonElement) => void; onWater: (chip: HTMLButtonElement) => void }) {
  return (
    <div className="map-chips" role="group" aria-label="Find on the map">
      <button type="button" className="chip map-chip" onClick={(event) => onFood(event.currentTarget)}>
        <Icon name="food" size={18} />
        Food
      </button>
      <button type="button" className="chip map-chip" onClick={(event) => onWater(event.currentTarget)}>
        <Icon name="water" size={18} />
        Water
      </button>
    </div>
  );
}
