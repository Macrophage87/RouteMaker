/**
 * Go (UI-CLEANUP, the owner's commute view; lib/appMode.ts): the phone's few-steps view, as the approved
 * mockup of 2026-10-11 draws it. Over the map, a top bar (Menu, the Go/Plan switch, Layers, Locate); at the
 * bottom, a sheet with one Where to? box, four place chips (Home, Food, Water, Restroom: the owner's
 * choice 3), the commute ride types (choice 10), and once a route is shown its time, stress bar, one alert
 * and Start. Every other control is in the Menu, the Ride sheet or Plan, two presses away at most.
 *
 * Plan keeps the full panel; its map has Food and Water chips (PlanMapChips), where Go has place chips.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "../Icon.tsx";
import { PlaceSearch } from "../PlaceSearch.tsx";
import type { LonLat } from "../lib/geo.ts";
import type { GeoGate, Place, PlaceChoice } from "../lib/geocode.ts";
import { MODE_LABEL, MODE_SWITCH_HINT, MODE_SWITCH_HINT_REVIEW, MODE_SWITCH_NAME, type AppMode } from "../lib/appMode.ts";
import { HOME_NOT_SET, type Home } from "../lib/myGo.ts";
import { BEST_ORDER_LABEL } from "../lib/stopOrder.ts";
import { CHANGE_HOME_TEXT, CLEAR_HOME_TEXT, HOME_PICK_LINE, PICK_ON_MAP_TEXT, homeClosesSheet, homeName, homeSetKey } from "../lib/homeSet.ts";

export type GoSheetSize = "peek" | "half" | "full";

/** The handle's next size: peek, half, full, then back to peek. */
export function nextSheetSize(size: GoSheetSize): GoSheetSize {
  return size === "peek" ? "half" : size === "half" ? "full" : "peek";
}

const SIZE_SAID: Record<GoSheetSize, string> = { peek: "small", half: "half height", full: "full height" };

/**
 * Go or Plan: two toggle buttons, the pressed one the view in use (the owner's choice 1: either view can switch). For
 * someone who may review, both switches (Go's bar and the panel's) have a third, Review (lib/appMode.ts switchModes).
 */
export function ModeSwitch({
  mode,
  onChange,
  className = "",
  modes = ["go", "plan"],
}: {
  mode: AppMode;
  onChange: (next: AppMode) => void;
  className?: string;
  modes?: readonly AppMode[];
}) {
  const hintId = useId();
  return (
    <div className={`mode-switch ${className}`.trim()} role="group" aria-label={MODE_SWITCH_NAME} aria-describedby={hintId}>
      {modes.map((m) => (
        <button key={m} type="button" className="mode-button" aria-pressed={mode === m} onClick={() => onChange(m)}>
          {MODE_LABEL[m]}
        </button>
      ))}
      <span id={hintId} hidden>
        {modes.includes("review") ? MODE_SWITCH_HINT_REVIEW : MODE_SWITCH_HINT}
      </span>
    </div>
  );
}

/** Go's bar over the map: Menu, the switch, Layers and Locate, and the destination once there is one. */
/** Go's bar: Undo and Redo, the big button (Start ride, or Route while the plan has changed), and Clear. */
export interface GoBar {
  onUndo: (() => void) | null;
  onRedo: (() => void) | null;
  /** Start ride on a route ready to ride; Route (or Routing…) otherwise; null when neither applies. */
  big: { label: string; start: boolean; busy: boolean; onPress: () => void } | null;
  onClear: (() => void) | null;
}

export function GoTopBar({
  mode,
  onMode,
  modes,
  onMenu,
  onLayers,
  onLocate,
  locating,
  destination,
  bar,
}: {
  mode: AppMode;
  onMode: (next: AppMode) => void;
  /** The switch's views (lib/appMode.ts switchModes): an admin's include Review, as in Plan's switch. */
  modes: readonly AppMode[];
  onMenu: (button: HTMLButtonElement) => void;
  onLayers: (button: HTMLButtonElement) => void;
  onLocate: () => void;
  locating: boolean;
  /** The plan's destination's name, or null with no plan (names the bar's group for a screen reader). */
  destination: string | null;
  /** Go's bar under the top row, as Plan's over the map (the owner, 2026-10-18: "mirror what plan does in general,
   * but instead of route, we start the ride"); null when it has nothing to offer. */
  bar: GoBar | null;
}) {
  return (
    <nav className="go-top" aria-label="Go">
      <div className="go-top-row">
        <button type="button" className="icon-button go-menu" onClick={(event) => onMenu(event.currentTarget)}>
          <Icon name="menu" />
          <span className="icon-button-label">Menu</span>
        </button>
        <ModeSwitch mode={mode} onChange={onMode} modes={modes} />
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
      {bar !== null && (
        <div className="go-destination" role="group" aria-label="Route and edits">
          {/* The route card shows where to; said here too, as the bar starts the ride there. */}
          {destination !== null && <span className="go-destination-name visually-hidden">To {destination}</span>}
          {bar.onUndo && (
            <button type="button" className="secondary plan-bar-small" data-history="undo" onClick={bar.onUndo} aria-label="Undo" title="Undo">
              <Icon name="undo" size={20} />
            </button>
          )}
          {bar.onRedo && (
            <button type="button" className="secondary plan-bar-small" data-history="redo" onClick={bar.onRedo} aria-label="Redo" title="Redo">
              <Icon name="redo" size={20} />
            </button>
          )}
          {bar.big && (
            <button
              type="button"
              className={bar.big.start ? "plan-bar-route go-bar-start" : "plan-bar-route"}
              aria-disabled={bar.big.busy ? true : undefined}
              onClick={() => {
                if (!bar.big?.busy) bar.big?.onPress();
              }}
            >
              <Icon name={bar.big.start ? "play" : "routes"} size={20} />
              {bar.big.label}
            </button>
          )}
          {bar.onClear && destination !== null && (
            <button type="button" className="secondary plan-bar-small go-clear" onClick={bar.onClear} aria-label={`Clear the route to ${destination}`} title="Clear">
              <Icon name="trash" size={20} />
            </button>
          )}
        </div>
      )}
    </nav>
  );
}

export interface GoPlaces {
  /** With a Home (the account's, or this device's signed out): the chip rides there. Else it opens the Home sheet. */
  homeReady: boolean;
  /** The Home there is, or null: the Home sheet shows it. */
  home: Home | null;
  /** The Home sheet's search picked a place. */
  onHomePlace: (place: Place) => void;
  onClearHome: () => void;
  /** The Home sheet's "Pick on the map": the next tap on the map is Home (pressed again, it is not). */
  homePicking: boolean;
  onPickHome: () => void;
  signedIn: boolean;
  onHome: (chip: HTMLButtonElement) => void;
  onFood: (chip: HTMLButtonElement) => void;
  onWater: (chip: HTMLButtonElement) => void;
  onRestroom: (chip: HTMLButtonElement) => void;
  /** Behind More (v0.7.0, the owner 2026-10-14: "Make sure that go stays clean"): the nearest repair stands and shops. */
  onRepair: (chip: HTMLButtonElement) => void;
  /** Behind More: the nearest places to see (Plan's Places to see, five of them, no filters). */
  onSights: (chip: HTMLButtonElement) => void;
}

/**
 * The Home sheet (lib/homeSet.ts): the place search, and in Go "Pick on the map"; with a Home, its name and Clear
 * Home. One place to set, change and clear Home: Go's Home chip (no Home yet) or More's Change Home, and Settings.
 * Nothing here takes the focus, except Clear Home's own when it goes with the Home: the search box then has it.
 */
export function HomeSetter({
  home,
  geoGate,
  searchBias,
  onPlace,
  onClear,
  picking = false,
  onPickOnMap,
}: {
  home: Home | null;
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
  onPlace: (place: Place) => void;
  onClear: () => void;
  picking?: boolean;
  /** Go only: the map way (Settings covers the map). */
  onPickOnMap?: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  return (
    <div className="home-setter" ref={box}>
      {home && (
        <p className="home-now">
          <strong>Home: </strong>
          {homeName(home)}
        </p>
      )}
      <PlaceSearch variant="home" pointCount={0} full={false} gate={geoGate} bias={searchBias} onPick={(place: Place) => onPlace(place)} />
      <div className="actions home-actions">
        {onPickOnMap && (
          <button type="button" className="secondary" aria-pressed={picking} onClick={onPickOnMap}>
            <Icon name="pin" size={18} />
            {PICK_ON_MAP_TEXT}
          </button>
        )}
        {home && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              onClear();
              // The button goes with the Home: the focus goes to the search box beside it, not to the page.
              box.current?.querySelector<HTMLInputElement>("input")?.focus();
            }}
          >
            {CLEAR_HOME_TEXT}
          </button>
        )}
      </div>
      {picking && <p className="hint home-pick-line">{HOME_PICK_LINE}</p>}
    </div>
  );
}

/**
 * Go's "Add a stop" (v0.7.0, "Keep adding stops by search"): one field in the route sheet, under the route card
 * (kept there one tap away, Stephen 2026-10-18); a place picked is a stop where it adds the least distance, routed at once (Undo removes it). Best order sits
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

/**
 * Go's route card (edit-route redesign, Stephen 2026-10-18): the start and the destination, and the stops between
 * them counted, on one button that opens Edit route (Plan's points in a sheet: change the start or the destination,
 * add or remove a stop, Swap, Loop). It replaced "Add a stop" under Start, and with a route the start was not shown.
 */
export function GoRouteCard({ start, destination, stops, onEdit }: { start: string; destination: string; stops: number; onEdit: (opener: HTMLButtonElement) => void }) {
  return (
    <button type="button" className="go-route-card" onClick={(event) => onEdit(event.currentTarget)}>
      <span className="go-route-ends">
        <span className="go-route-end">
          <Icon name="play" size={16} />
          <span className="visually-hidden">From </span>
          {start}
        </span>
        {stops > 0 && <span className="go-route-stops">{stops === 1 ? "1 stop" : `${stops} stops`}</span>}
        <span className="go-route-end go-route-to">
          <Icon name="pin" size={16} />
          <span className="visually-hidden">to </span>
          {destination}
        </span>
      </span>
      <span className="go-route-edit">
        <Icon name="edit" size={16} />
        Edit route
      </span>
    </button>
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
  startLine,
  startMissing,
  onStartPick,
}: {
  size: GoSheetSize;
  onSize: (next: GoSheetSize) => void;
  pointCount: number;
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
  onPick: (place: Place) => void;
  /** The top result of Where to? while the rider looks at it: Go starts routing there early (v0.7.0, "Faster routing"). */
  onTopPlace?: (place: Place) => void;
  places: GoPlaces;
  /** The ride type chips (RideChips), before there is a route; with one, the route holds them. */
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
  const homeSheetId = useId();
  // The Home sheet: the Home chip opens it while there is no Home, More's Change Home once there is one.
  const [homeOpen, setHomeOpen] = useState(false);
  const homeShown = homeOpen || places.homePicking;
  // Home set from the sheet (its search or the map): the sheet closes and the focus goes back to the Home chip,
  // which now rides Home (review F3). A Home cleared keeps the sheet open, for the next one.
  const homeChip = useRef<HTMLButtonElement>(null);
  const homeKey = homeSetKey(places.home);
  const lastHomeKey = useRef(homeKey);
  useEffect(() => {
    const was = lastHomeKey.current;
    lastHomeKey.current = homeKey;
    if (!homeClosesSheet(was, homeKey, homeOpen)) return;
    setHomeOpen(false);
    homeChip.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per Home set, not per render
  }, [homeKey]);
  const startBoxId = useId();
  const moreId = useId();
  const [startOpen, setStartOpen] = useState(false);
  // More: one chip at the row's end that shows the rest (Repair, Sights); later additions go here, not on the row.
  const [moreOpen, setMoreOpen] = useState(false);
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
            ref={homeChip}
            type="button"
            className="chip place-chip"
            onClick={(event) => (places.homeReady ? places.onHome(event.currentTarget) : setHomeOpen(!homeOpen))}
            aria-expanded={places.homeReady ? undefined : homeShown}
            aria-controls={places.homeReady ? undefined : homeSheetId}
            aria-describedby={places.homeReady || homeShown ? undefined : homeHint}
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
          <button type="button" className="chip place-chip go-more" aria-expanded={moreOpen} aria-controls={moreId} onClick={() => setMoreOpen(!moreOpen)}>
            <Icon name="more" size={18} />
            More
          </button>
        </div>
        <div id={moreId} className="chip-row go-places go-more-row" role="group" aria-label="More places" hidden={!moreOpen}>
          <button type="button" className="chip place-chip" onClick={(event) => places.onRepair(event.currentTarget)}>
            <Icon name="wrench" size={18} />
            Repair
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onSights(event.currentTarget)}>
            <Icon name="camera" size={18} />
            Sights
          </button>
          {places.homeReady && (
            <button type="button" className="chip place-chip" aria-expanded={homeShown} aria-controls={homeSheetId} onClick={() => setHomeOpen(!homeOpen)}>
              <Icon name="home" size={18} />
              {CHANGE_HOME_TEXT}
            </button>
          )}
        </div>
        <div id={homeSheetId} className="go-home-sheet" role="group" aria-label="Home" hidden={!homeShown}>
          {homeShown && (
            <HomeSetter
              home={places.home}
              geoGate={geoGate}
              searchBias={searchBias}
              onPlace={places.onHomePlace}
              onClear={places.onClearHome}
              picking={places.homePicking}
              onPickOnMap={places.onPickHome}
            />
          )}
        </div>
        {/* One short line, and only while there is no Home and its sheet is shut: the Home chip's description, said
            with it and kept out of sight, so the sheet fits one phone screen (the owner, 2026-10-17). */}
        {!places.homeReady && !homeShown && (
          <p id={homeHint} className="visually-hidden go-home-hint">
            {HOME_NOT_SET}
          </p>
        )}
        {!routeShown && rides}
      </div>
      {/* With a route, the ride types are in it, under the route card (edit-route redesign, Stephen 2026-10-18). */}
      {/* Said by the app's own region (Go has no Points section's status line; App noticeSaidElsewhere). */}
      {notice && <p className="go-notice notice">{notice}</p>}
    </div>
  );
}

/** Plan's map chips (the mockup's Plan view): Food, Water and Places to see open their sheets in the panel. */
export function PlanMapChips({
  onFood,
  onWater,
  onPlaces,
}: {
  onFood: (chip: HTMLButtonElement) => void;
  onWater: (chip: HTMLButtonElement) => void;
  onPlaces: (chip: HTMLButtonElement) => void;
}) {
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
      <button type="button" className="chip map-chip" onClick={(event) => onPlaces(event.currentTarget)}>
        <Icon name="camera" size={18} />
        Places to see
      </button>
    </div>
  );
}
