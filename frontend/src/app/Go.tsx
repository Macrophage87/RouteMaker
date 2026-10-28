/**
 * Go (UI-CLEANUP, the owner's commute view; lib/appMode.ts): the phone's few-steps view, as the approved
 * mockup of 2026-10-11 draws it. Over the map, a top bar (Settings, the Go/Plan switch, Layers, Locate); at the
 * bottom, a sheet with one Where to? box, four place chips (Home, Eat, Water, Restroom: the owner's
 * choice 3), the commute ride types (choice 10), and once a route is shown its time, stress bar, one alert
 * and Start. Every other control is in Settings, the Ride sheet or Plan, two presses away at most.
 *
 * Plan keeps the full panel; its map has Eat, Water and Places to see chips (PlanMapChips), where Go has place chips.
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
import { FEATURED_ROUTES_LABEL, FEATURED_ROUTES_PATH } from "../lib/featuredRoutes.ts";
import { LOAD_ROUTE } from "../lib/loadRoute.ts";
import {
  ADD_FAVORITE_TEXT,
  DONE_EDITING_TEXT,
  EDIT_FAVORITES_TEXT,
  FAVORITES_LOADING,
  FAVORITES_TEXT,
  SET_HOME_TEXT,
  SET_WORK_TEXT,
  WORK_TEXT,
  favoriteName,
  othersOf,
  workOf,
  type FavoritePlace,
} from "../lib/favoritePlaces.ts";
import { t } from "../lib/i18n.ts";

export type GoSheetSize = "peek" | "half" | "full";

/** The handle's next size: peek, half, full, then back to peek. */
export function nextSheetSize(size: GoSheetSize): GoSheetSize {
  return size === "peek" ? "half" : size === "half" ? "full" : "peek";
}

const SIZE_SAID: Record<GoSheetSize, string> = { peek: t("small"), half: t("half height"), full: t("full height") };

/**
 * The sheet's handle on a phone: a bar to tap for the next size, peek, half, full, then back to peek. Go's sheet and
 * Plan's panel share it (P10); `controls` and `expanded` where a size hides part of the sheet (Plan's peek hides
 * its body, as Hide planner did).
 */
export function SheetHandle({
  size,
  onSize,
  controls,
  expanded,
}: {
  size: GoSheetSize;
  onSize: (next: GoSheetSize) => void;
  controls?: string;
  expanded?: boolean;
}) {
  const next = nextSheetSize(size);
  return (
    <button
      type="button"
      className="go-handle"
      onClick={() => onSize(next)}
      aria-controls={controls}
      aria-expanded={expanded}
      aria-label={t("Sheet: {size}. Make it {next}", { size: SIZE_SAID[size], next: SIZE_SAID[next] })}
    >
      <span className="go-handle-bar" aria-hidden="true" />
    </button>
  );
}

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

/** Go's bar over the map: Settings, the switch, Layers and Locate, and the destination once there is one. */
/** Go's bar: Undo and Redo, the big button (Route while the plan has changed, or Roam), and Clear. */
export interface GoBar {
  onUndo: (() => void) | null;
  onRedo: (() => void) | null;
  /**
   * Route (or Routing…) while the plan has changed; Roam with no destination; null otherwise. A route ready to ride
   * has none: its Start ride is the sheet's alone (one Start ride per screen, the owner's P1).
   */
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
    <nav className="go-top" aria-label={t("Go")}>
      <div className="go-top-row">
        <button type="button" className="icon-button go-menu" onClick={(event) => onMenu(event.currentTarget)}>
          <Icon name="gear" />
          <span className="icon-button-label">{t("Settings")}</span>
        </button>
        <ModeSwitch mode={mode} onChange={onMode} modes={modes} />
        <span className="go-top-end">
          <button type="button" className="icon-button go-layers" onClick={(event) => onLayers(event.currentTarget)}>
            <Icon name="layers" />
            <span className="icon-button-label">{t("Layers")}</span>
          </button>
          <button type="button" className="icon-button go-locate" onClick={onLocate} aria-disabled={locating || undefined}>
            <Icon name="locate" />
            <span className="icon-button-label">{locating ? t("Locating…") : t("Locate")}</span>
          </button>
        </span>
      </div>
      {bar !== null && (
        <div className="go-destination" role="group" aria-label={t("Route and edits")}>
          {/* The route card shows where to; said here too, as the bar starts the ride there. */}
          {destination !== null && <span className="go-destination-name visually-hidden">{t("To {place}", { place: destination })}</span>}
          {bar.onUndo && (
            <button type="button" className="secondary plan-bar-small" data-history="undo" onClick={bar.onUndo} aria-label={t("Undo")} title={t("Undo")}>
              <Icon name="undo" size={20} />
            </button>
          )}
          {bar.onRedo && (
            <button type="button" className="secondary plan-bar-small" data-history="redo" onClick={bar.onRedo} aria-label={t("Redo")} title={t("Redo")}>
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
            <button type="button" className="secondary plan-bar-small go-clear" onClick={bar.onClear} aria-label={t("Clear the route to {place}", { place: destination })} title={t("Clear")}>
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
  /**
   * Signed in (lib/favoritePlaces.ts): the account's favorite places, Work among them. The Home chip is then a
   * Favorites chip whose popout lists Home, Work and these.
   */
  favorites: readonly FavoritePlace[] | null;
  /** Favorites opened: the account's list is read again if it has not been (null). */
  onFavoritesOpen: () => void;
  onFavorite: (place: FavoritePlace) => void;
  /** A place searched in the popout: saved as a favorite, or as Work. */
  onAddFavorite: (place: Place, work: boolean) => void;
  onRemoveFavorite: (place: FavoritePlace) => void;
  onFood: (chip: HTMLButtonElement) => void;
  onWater: (chip: HTMLButtonElement) => void;
  onRestroom: (chip: HTMLButtonElement) => void;
  /** Behind More (the owner, 2026-10-19: "Metro stops should be on the list in more"): the nearest Metro stations, in Nearest. */
  onMetro: (chip: HTMLButtonElement) => void;
  /** Behind More (v0.7.0, the owner 2026-10-14: "Make sure that go stays clean"): the nearest repair stands and shops. */
  onRepair: (chip: HTMLButtonElement) => void;
  /** Behind More: the nearest places to see (Plan's Places to see, five of them, no filters). */
  onSights: (chip: HTMLButtonElement) => void;
  /** Behind More (the owner, 2026-10-26): the rider's saved and kept routes, Load route's popup; a tap on one opens it in Go. */
  onSavedRoutes: () => void;
}

/**
 * The Favorites popout (lib/favoritePlaces.ts; Stephen 2026-10-26: "just have a favorites replace home", "Home and if
 * set work would be the top 2 favorites", "we'd have a popout"): signed in, Go's Favorites chip opens it. One row per
 * place, Home first, then Work, then the rest; a tap rides there. Set Home opens the Home sheet as the Home chip did;
 * Set Work and Add a place open one search box here. Edit shows Change Home, Remove beside each place, and Done.
 */
export function FavoritesPopout({
  id,
  homeSheetId,
  places,
  geoGate,
  searchBias,
  homeSheetOpen,
  onHomeSheet,
  onRide,
}: {
  id: string;
  /** The Home sheet Set Home and Change open. */
  homeSheetId: string;
  places: GoPlaces;
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
  homeSheetOpen: boolean;
  /** Set Home, or (editing) Change Home: the Home sheet, opened or shut. */
  onHomeSheet: (open: boolean) => void;
  /** A row was ridden: the popout closes. */
  onRide: () => void;
}) {
  const [adding, setAdding] = useState<"" | "place" | "work">("");
  const [editing, setEditing] = useState(false);
  // Null until the account's list is read: Home only, and a line that says the rest are loading.
  const loaded = places.favorites !== null;
  const work = workOf(places.favorites ?? []);
  const others = othersOf(places.favorites ?? []);
  const home = places.home;
  // A Remove, or a place picked, takes its button or the search box away: the focus goes to Add a place, not the page.
  const addChip = useRef<HTMLButtonElement>(null);
  const ride = (go: () => void) => {
    setAdding("");
    setEditing(false);
    go();
    onRide();
  };
  const searchId = useId();
  return (
    <div id={id} className="go-favorites" role="group" aria-label={FAVORITES_TEXT}>
      <ul className="go-favorites-list">
        <li>
          {home ? (
            <button type="button" className="go-favorite" onClick={(event) => ride(() => places.onHome(event.currentTarget))}>
              <Icon name="home" size={18} />
              <span className="go-favorite-kind">{t("Home")}</span>
              <span className="go-favorite-name">{homeName(home)}</span>
            </button>
          ) : (
            <button type="button" className="go-favorite go-favorite-unset" aria-expanded={homeSheetOpen} aria-controls={homeSheetId} onClick={() => onHomeSheet(!homeSheetOpen)}>
              <Icon name="home" size={18} />
              {SET_HOME_TEXT}
            </button>
          )}
          {home && editing && (
            <button type="button" className="secondary" aria-expanded={homeSheetOpen} aria-controls={homeSheetId} onClick={() => onHomeSheet(!homeSheetOpen)}>
              {t("Change")}<span className="visually-hidden"> {t("Home")}</span>
            </button>
          )}
        </li>
        {!loaded && <li className="hint">{FAVORITES_LOADING}</li>}
        {loaded && (
        <li>
          {work ? (
            <button type="button" className="go-favorite" onClick={() => ride(() => places.onFavorite(work))}>
              <Icon name="work" size={18} />
              <span className="go-favorite-kind">{WORK_TEXT}</span>
              <span className="go-favorite-name">{favoriteName(work)}</span>
            </button>
          ) : (
            <button
              type="button"
              className="go-favorite go-favorite-unset"
              aria-expanded={adding === "work"}
              aria-controls={searchId}
              onClick={() => setAdding(adding === "work" ? "" : "work")}
            >
              <Icon name="work" size={18} />
              {SET_WORK_TEXT}
            </button>
          )}
          {work && editing && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                places.onRemoveFavorite(work);
                addChip.current?.focus();
              }}
            >
              {t("Remove")}<span className="visually-hidden"> {t("Work")}</span>
            </button>
          )}
        </li>
        )}
        {others.map((place) => (
          <li key={`${place.point[0]},${place.point[1]}`}>
            <button type="button" className="go-favorite" onClick={() => ride(() => places.onFavorite(place))}>
              <Icon name="star" size={18} />
              <span className="go-favorite-name">{favoriteName(place)}</span>
            </button>
            {editing && (
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  places.onRemoveFavorite(place);
                  addChip.current?.focus();
                }}
              >
                {t("Remove")}<span className="visually-hidden"> {favoriteName(place)}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
      {loaded && (
      <div className="chip-row go-favorites-actions">
        <button ref={addChip} type="button" className="chip" aria-expanded={adding === "place"} aria-controls={searchId} onClick={() => setAdding(adding === "place" ? "" : "place")}>
          <Icon name="plus" size={18} />
          {ADD_FAVORITE_TEXT}
        </button>
        {/* Its name says what a press does (Edit, then Done): no pressed state as well. */}
        {(home || (places.favorites ?? []).length > 0) && (
          <button type="button" className="chip" onClick={() => setEditing(!editing)}>
            {editing ? DONE_EDITING_TEXT : EDIT_FAVORITES_TEXT}
          </button>
        )}
      </div>
      )}
      <div id={searchId} hidden={adding === ""}>
        {adding !== "" && (
          <PlaceSearch
            key={adding}
            variant={adding === "work" ? "work" : "favorite"}
            pointCount={0}
            full={false}
            gate={geoGate}
            bias={searchBias}
            onPick={(place: Place) => {
              places.onAddFavorite(place, adding === "work");
              setAdding("");
              addChip.current?.focus();
            }}
          />
        )}
      </div>
    </div>
  );
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
          <strong>{t("Home:")} </strong>
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
 * Go's "Add a stop" (v0.7.0, "Keep adding stops by search"): "+ Add a stop" in the route sheet, under the route card
 * (kept there one tap away, Stephen 2026-10-18), opens one field; a place picked is a stop where it adds the least
 * distance, routed at once (Undo removes it). Best order sits beside it with two or more stops; it is the field's only
 * company, so Go stays one control per feature.
 */
export function GoAddStop({
  geoGate,
  searchBias,
  searchOrigin,
  onPick,
  full,
  orderShown,
  ordering,
  onBestOrder,
}: {
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
  /** The route's start: stops found are listed nearest it first, with their distances (P2). */
  searchOrigin: () => LonLat | undefined;
  onPick: (place: Place) => void;
  full: boolean;
  orderShown: boolean;
  ordering: boolean;
  onBestOrder: () => void;
}) {
  // "+ Add a stop" opens the field with the focus in it (the owner's P1, 2026-10-28: the field was always shown); a
  // place picked, or Escape on the empty box, puts it away with the focus back on the button.
  const [open, setOpen] = useState(false);
  const fieldId = useId();
  const input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  const close = () => {
    setOpen(false);
    opener.current?.focus();
  };
  const pickStop = (place: Place) => {
    onPick(place);
    close();
  };
  return (
    <div className="go-add-stop">
      <button ref={opener} type="button" className="link go-add-stop-open" aria-expanded={open} aria-controls={fieldId} onClick={() => setOpen(!open)}>
        <Icon name="plus" size={18} />
        {t("Add a stop")}
      </button>
      <div id={fieldId} className="go-add-stop-field" hidden={!open}>
        {open && (
          <PlaceSearch variant="stop" pointCount={2} full={full} gate={geoGate} bias={searchBias} origin={searchOrigin} inputRef={input} onDismiss={close} onPick={(place: Place) => pickStop(place)} />
        )}
      </div>
      {orderShown && (
        <button type="button" className="secondary" onClick={onBestOrder} aria-disabled={ordering ? true : undefined}>
          {BEST_ORDER_LABEL}
        </button>
      )}
    </div>
  );
}

/**
 * Go's route card (edit-route redesign, Stephen 2026-10-18): the start and the destination, and the stops and via
 * points between them counted apart (lib/pointKinds.ts middleCountSaid), on one button that opens Edit route
 * (Plan's points in a sheet: change the start or the destination, add or remove a stop, Swap, Loop). It replaced "Add a stop" under Start, and with a route the start was not shown.
 */
export function GoRouteCard({ start, destination, between, onEdit }: { start: string; destination: string; between: string; onEdit: (opener: HTMLButtonElement) => void }) {
  return (
    <button type="button" className="go-route-card" onClick={(event) => onEdit(event.currentTarget)}>
      <span className="go-route-ends">
        <span className="go-route-end">
          <Icon name="play" size={16} />
          <span className="visually-hidden">{t("From")} </span>
          {start}
        </span>
        {between && <span className="go-route-stops">{between}</span>}
        <span className="go-route-end go-route-to">
          <Icon name="pin" size={16} />
          <span className="visually-hidden">{t("to")} </span>
          {destination}
        </span>
      </span>
      <span className="go-route-edit">
        <Icon name="edit" size={16} />
        {t("Edit route")}
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
  searchOrigin,
  onPick,
  onTopPlace,
  onWhereToFocus,
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
  /** The route's start (the rider's location or the start typed in): Where to? lists places nearest it first, with their distances (P2). */
  searchOrigin: () => LonLat | undefined;
  onPick: (place: Place) => void;
  /** The top result of Where to? while the rider looks at it: Go starts routing there early (v0.7.0, "Faster routing"); null with none. */
  onTopPlace?: (place: Place | null) => void;
  /** Where to? takes the focus: Go warms the location up in the background (routing audit S28). */
  onWhereToFocus?: () => void;
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
  // Signed in: the Favorites popout, in the Home chip's place.
  const favoritesId = useId();
  const [favoritesOpen, setFavoritesOpen] = useState(false);
  const [startOpen, setStartOpen] = useState(false);
  // More: one chip at the row's end that shows the rest (Metro, Repair, Places to see, Load route); later additions go here, not on the row.
  const [moreOpen, setMoreOpen] = useState(false);
  const startShown = startOpen || startMissing;
  const routeShown = route !== null;
  // Under a route, Where to? and the place chips fold into one "New destination" row (the owner's P1, 2026-10-28:
  // they repeated under the route and made the sheet about two screens); a place picked folds them again.
  const [newOpen, setNewOpen] = useState(false);
  const newId = useId();
  const whereShown = !routeShown || newOpen;
  useEffect(() => {
    if (!routeShown) setNewOpen(false);
  }, [routeShown]);
  const pickWhereTo = (place: Place) => {
    setNewOpen(false);
    onPick(place);
  };
  return (
    <div className={`go-sheet go-${size}`}>
      <SheetHandle size={size} onSize={onSize} />
      {/* Where to? stays first while there is no route; with one, the route comes first (it is what the rider is
          looking at), and Where to? follows for a new place, behind New destination. */}
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
                {t("Change start")}
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
              origin={searchOrigin}
              onPick={(place: Place, _choice: PlaceChoice) => {
                setStartOpen(false);
                onStartPick(place);
              }}
            />
          </div>
        )}
        {routeShown && (
          <button type="button" className="secondary go-new-destination" aria-expanded={newOpen} aria-controls={newId} onClick={() => setNewOpen(!newOpen)}>
            <Icon name="search" size={18} />
            {t("New destination")}
          </button>
        )}
        <div id={newId} className="go-new-body" hidden={!whereShown}>
        <PlaceSearch variant="go" pointCount={pointCount} full={false} gate={geoGate} bias={searchBias} origin={searchOrigin} onPick={(place: Place, _choice: PlaceChoice) => pickWhereTo(place)} onTopPlace={onTopPlace} onFocusBox={onWhereToFocus} />
        <div className="chip-row go-places" role="group" aria-label={t("Places")}>
          {places.signedIn ? (
            // Signed in, Home is the first of the rider's favorites (Stephen 2026-10-26: "just have a favorites replace home").
            <button
              ref={homeChip}
              type="button"
              className="chip place-chip"
              aria-expanded={favoritesOpen}
              aria-controls={favoritesId}
              onClick={() => {
                if (favoritesOpen) setHomeOpen(false);
                else places.onFavoritesOpen();
                setFavoritesOpen(!favoritesOpen);
              }}
            >
              <Icon name="star" size={18} />
              {FAVORITES_TEXT}
            </button>
          ) : (
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
              {t("Home")}
            </button>
          )}
          {/* "Eat", not "Food" (P2): the sheet lists restaurants and cafes, and a rider looking for a grocery store tried it first. */}
          <button type="button" className="chip place-chip" onClick={(event) => places.onFood(event.currentTarget)}>
            <Icon name="food" size={18} />
            {t("Eat")}
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onWater(event.currentTarget)}>
            <Icon name="water" size={18} />
            {t("Water")}
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onRestroom(event.currentTarget)}>
            <Icon name="wc" size={18} />
            {t("Restroom")}
          </button>
          <button type="button" className="chip place-chip go-more" aria-expanded={moreOpen} aria-controls={moreId} onClick={() => setMoreOpen(!moreOpen)}>
            <Icon name="more" size={18} />
            {t("More")}
          </button>
        </div>
        <div id={moreId} className="chip-row go-places go-more-row" role="group" aria-label={t("More places")} hidden={!moreOpen}>
          <button type="button" className="chip place-chip" onClick={(event) => places.onMetro(event.currentTarget)}>
            <Icon name="train" size={18} />
            {t("Metro")}
          </button>
          <button type="button" className="chip place-chip" onClick={(event) => places.onRepair(event.currentTarget)}>
            <Icon name="wrench" size={18} />
            {t("Repair")}
          </button>
          {/* Places to see, as Plan's chip and the layer say it (P12: it was "Sights"). */}
          <button type="button" className="chip place-chip" onClick={(event) => places.onSights(event.currentTarget)}>
            <Icon name="camera" size={18} />
            {t("Places to see")}
          </button>
          <button type="button" className="chip place-chip" aria-haspopup="dialog" onClick={places.onSavedRoutes}>
            <Icon name="routes" size={18} />
            {LOAD_ROUTE}
          </button>
          {/* Featured routes (the owner, 2026-10-19: "one item behind More"): the posts' list, a page of its own (core/route_posts.py). */}
          <a className="chip place-chip" href={FEATURED_ROUTES_PATH}>
            <Icon name="star" size={18} />
            {FEATURED_ROUTES_LABEL}
          </a>
          {/* Signed in, Favorites' Edit changes Home. */}
          {places.homeReady && !places.signedIn && (
            <button type="button" className="chip place-chip" aria-expanded={homeShown} aria-controls={homeSheetId} onClick={() => setHomeOpen(!homeOpen)}>
              <Icon name="home" size={18} />
              {CHANGE_HOME_TEXT}
            </button>
          )}
        </div>
        {places.signedIn && favoritesOpen && (
          <FavoritesPopout
            id={favoritesId}
            homeSheetId={homeSheetId}
            places={places}
            geoGate={geoGate}
            searchBias={searchBias}
            homeSheetOpen={homeShown}
            onHomeSheet={setHomeOpen}
            onRide={() => {
              // The row pressed goes with the popout: the focus goes back to the Favorites chip, not the page.
              setFavoritesOpen(false);
              homeChip.current?.focus();
            }}
          />
        )}
        <div id={homeSheetId} className="go-home-sheet" role="group" aria-label={t("Home")} hidden={!homeShown}>
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
        {!places.signedIn && !places.homeReady && !homeShown && (
          <p id={homeHint} className="visually-hidden go-home-hint">
            {HOME_NOT_SET}
          </p>
        )}
        </div>
        {!routeShown && rides}
      </div>
      {/* With a route, the ride types are in it, under the route card (edit-route redesign, Stephen 2026-10-18). */}
      {/* Said by the app's own region (Go has no Points section's status line; App noticeSaidElsewhere). */}
      {notice && <p className="go-notice notice">{notice}</p>}
    </div>
  );
}

/**
 * Plan's map chips (the mockup's Plan view): Food, Water and Places to see open their sheets in the panel. They fold
 * behind one Find chip (the owner, 2026-10-21: "The food water places to see might want to be on an expansion
 * button ... It's more room"); a choice folds them again, and Escape folds them with the focus back on Find.
 */
export function PlanMapChips({
  onFood,
  onWater,
  onPlaces,
}: {
  onFood: (chip: HTMLButtonElement) => void;
  onWater: (chip: HTMLButtonElement) => void;
  onPlaces: (chip: HTMLButtonElement) => void;
}) {
  const [open, setOpen] = useState(false);
  const rowId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  // The sheet a choice opens hands the focus back to Find (the chip it came from is folded away).
  const pick = (go: (chip: HTMLButtonElement) => void) => () => {
    setOpen(false);
    if (toggleRef.current) go(toggleRef.current);
  };
  return (
    <div
      className="map-chips"
      role="group"
      aria-label={t("Find on the map")}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          setOpen(false);
          toggleRef.current?.focus();
        }
      }}
    >
      <button type="button" ref={toggleRef} className="chip map-chip map-chips-toggle" aria-expanded={open} aria-controls={rowId} onClick={() => setOpen(!open)}>
        <Icon name="search" size={18} />
        {t("Find")}
      </button>
      <div id={rowId} className="map-chips-row" hidden={!open}>
        {/* "Eat", as Go's chip (P2, P12). */}
        <button type="button" className="chip map-chip" onClick={pick(onFood)}>
          <Icon name="food" size={18} />
          {t("Eat")}
        </button>
        <button type="button" className="chip map-chip" onClick={pick(onWater)}>
          <Icon name="water" size={18} />
          {t("Water")}
        </button>
        <button type="button" className="chip map-chip" onClick={pick(onPlaces)}>
          <Icon name="camera" size={18} />
          {t("Places to see")}
        </button>
      </div>
    </div>
  );
}
