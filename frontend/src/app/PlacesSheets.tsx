// v0.7.0's place sheets: Go's Repair and Sights (behind the More chip; the owner, 2026-10-14: "Make sure that go
// stays clean, but they can find it there. Plan can have more complexity"), and Plan's Places to see. Each list
// is lettered as the map's markers are (lib/letteredPlaces.ts); a row's one button rides there (Go) or adds the
// place as a stop. App.tsx keeps the state; the lists are lib/repair.ts's and lib/places.ts's.
import { useId, type ReactNode } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { setSource, tapCard, useMap } from "./mapOverlay.ts";
import { Icon } from "../Icon.tsx";
import { SheetFrame } from "../Sidebar.tsx";
import { placeLetter } from "../lib/letteredPlaces.ts";
import { formatDistance } from "../lib/format.ts";
import {
  REPAIR_ICON_ID,
  REPAIR_LAYER,
  REPAIR_NOTE,
  REPAIR_SOURCE_ID,
  repairDetails,
  repairGeoJson,
  repairIcon,
  repairLayer,
  repairTitle,
  type RepairNearby,
  type RepairPlace,
} from "../lib/repair.ts";
import {
  CATEGORIES,
  PLACES_LAYER,
  PLACES_NOTE,
  PLACES_PAGE,
  PLACES_SOURCE_ID,
  categoryOf,
  placesGeoJson,
  placesLayer,
  sightHowFar,
  sightText,
  type PlaceFilter,
  type SightPlace,
  type SightResult,
} from "../lib/places.ts";
import { WATER_MIN_ZOOM } from "../lib/waterRestrooms.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import { SHEET_TITLES, type PanelView } from "../lib/sidebar.ts";
import type { SheetNav } from "./Sheets.tsx";

/** Go's Repair: the nearest repair stands and bike shops, lettered; a row rides there. */
export function RepairSheet({ nav, status, items, at, onRide }: { nav: SheetNav; status: string; items: readonly RepairNearby[] | null; at: Date; onRide: (item: RepairNearby) => void }) {
  const rowId = useId();
  return (
    <SheetFrame id="sheet-repair" title={SHEET_TITLES.repair} open={nav.view === "repair"} onBack={nav.back} backLabel={nav.backLabel("repair")}>
      <p className="hint repair-status" role="status">
        {status}
      </p>
      {items && items.length > 0 && (
        <>
          <ol role="list" className="nearest-list repair-list" aria-label="Repair stands and bike shops">
            {items.map((item, i) => (
              <li key={item.place.id}>
                {/* Named by the place and how far; its details are its description (review F13), not repeated in the name. */}
                <button
                  type="button"
                  className="secondary place-row"
                  onClick={() => onRide(item)}
                  aria-label={`${placeLetter(i)}: Ride to ${repairTitle(item.place)}, ${formatDistance(item.metres)}`}
                  aria-describedby={`${rowId}-${i}`}
                >
                  <Icon name={item.place.kind === "stand" ? "wrench" : "shop"} size={18} />
                  <span>
                    <strong>
                      {placeLetter(i)}. {repairTitle(item.place)}
                    </strong>{" "}
                    {formatDistance(item.metres)}. <span id={`${rowId}-${i}`}>{repairDetails(item.place, at).join(" ")}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          <p className="hint">{REPAIR_NOTE}</p>
        </>
      )}
    </SheetFrame>
  );
}

/** One place's row: the letter, the category's emoji (decorative) and words, the name and how far. */
function SightRow({ result, index, children }: { result: SightResult; index: number; children?: ReactNode }) {
  const category = categoryOf(result.place);
  return (
    <span>
      <span aria-hidden="true" className="place-emoji">
        {category.emoji}
      </span>{" "}
      <strong>
        {placeLetter(index)}. {result.place.name}
      </strong>{" "}
      {category.one}. {sightHowFar(result)}.{children}
    </span>
  );
}

/** Go's Sights: the nearest five, no filters; a row adds it as a stop (with a route) or rides there. */
export function SightsList({ items, canAddStop, onPick }: { items: readonly SightResult[]; canAddStop: boolean; onPick: (result: SightResult) => void }) {
  return (
    <ol role="list" className="nearest-list sights-list" aria-label="Places to see">
      {items.map((r, i) => (
        <li key={r.place.id}>
          <button type="button" className="secondary place-row" onClick={() => onPick(r)} aria-label={`${placeLetter(i)}: ${canAddStop ? "Add as stop" : "Ride to"} ${sightText(r)}`}>
            <SightRow result={r} index={i} />
          </button>
        </li>
      ))}
    </ol>
  );
}

export interface PlacesSheetProps {
  nav: SheetNav;
  go: boolean;
  status: string;
  /** Go: the sights (at most five). Plan: the list so far (a page or more). */
  items: readonly SightResult[] | null;
  total: number;
  onMore: () => void;
  filter: PlaceFilter;
  onFilter: (filter: PlaceFilter) => void;
  canAddStop: boolean;
  onShow: (result: SightResult) => void;
  onAddStop: (result: SightResult) => void;
  /** Go: a row's one tap (a stop with a route, else the destination). */
  onGoPick: (result: SightResult) => void;
}

/** Plan's Places to see (filters, hours, website) and Go's Sights (the nearest five, one tap each). */
export function PlacesSheet(props: PlacesSheetProps) {
  const { nav, go, status, items, total, onMore, filter, onFilter, canAddStop, onShow, onAddStop, onGoPick } = props;
  return (
    <SheetFrame id="sheet-places" title={go ? GO_SIGHTS_TITLE : SHEET_TITLES.places} open={nav.view === "places"} onBack={nav.back} backLabel={nav.backLabel("places")}>
      {!go && (
        <label className="places-filter">
          Show{" "}
          <select value={filter} onChange={(event) => onFilter(event.target.value as PlaceFilter)}>
            <option value="all">All places to see</option>
            {CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <p className="hint places-status" role="status">
        {status}
      </p>
      {items && items.length > 0 && go && <SightsList items={items} canAddStop={canAddStop} onPick={onGoPick} />}
      {items && items.length > 0 && !go && (
        <ol role="list" className="nearest-list places-list" aria-label="Places to see">
          {items.map((r, i) => (
            <li key={r.place.id}>
              <SightRow result={r} index={i}>
                {r.place.hours ? ` Hours: ${r.place.hours}.` : ""}
              </SightRow>
              <span className="actions">
                <button type="button" className="secondary" aria-label={`Show on map: ${r.place.name}, marker ${placeLetter(i)}`} onClick={() => onShow(r)}>
                  Show on map
                </button>
                {canAddStop && (
                  <button type="button" className="secondary" aria-label={`Add as stop: ${r.place.name}`} onClick={() => onAddStop(r)}>
                    Add as stop
                  </button>
                )}
                {r.place.website && (
                  <a className="food-web" href={r.place.website} target="_blank" rel="noopener noreferrer" aria-label={`Website: ${r.place.name} (opens in a new tab)`}>
                    Website
                  </a>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
      {!go && items && items.length < total && (
        <button type="button" className="secondary food-more" onClick={onMore}>
          Show {Math.min(PLACES_PAGE, total - items.length)} more
        </button>
      )}
      {items && items.length > 0 && <p className="hint">{PLACES_NOTE}</p>}
    </SheetFrame>
  );
}

/** Go's name for the sheet, as its chip says it. */
export const GO_SIGHTS_TITLE = "Sights";

/** The views these sheets are, for App's lettered places. */
export const PLACE_VIEWS: readonly PanelView[] = ["repair", "places"];

// --- The map: repair stands (with the water layer's switch) and the places to see layer ------------

/** The repair stands, drawn with the Water and restrooms layer's switch (the owner: "just the stands"). */
export function RepairStandsOverlay({ getMap, places, on, pixelRatio }: { getMap: () => MapLibreMap | null; places: readonly RepairPlace[] | null; on: boolean; pixelRatio: number }) {
  useMap(
    getMap,
    (map) => {
      if (!places || !places.some((p) => p.kind === "stand")) return;
      if (!map.hasImage(REPAIR_ICON_ID)) {
        const { pixelRatio: ratio, ...image } = repairIcon(pixelRatio);
        map.addImage(REPAIR_ICON_ID, image, { pixelRatio: ratio });
      }
      setSource(map, REPAIR_SOURCE_ID, repairGeoJson(places));
      if (!map.getLayer(REPAIR_LAYER)) map.addLayer(repairLayer(WATER_MIN_ZOOM) as never, map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined);
      map.setLayoutProperty(REPAIR_LAYER, "visibility", on ? "visible" : "none");
      const byId = new Map(places.map((p) => [p.id, p]));
      return tapCard(map, REPAIR_LAYER, (id) => {
        const p = byId.get(id);
        if (!p) return null;
        return [repairTitle(p), ...repairDetails(p, new Date()), "From OpenStreetMap: check it is working before you count on it."];
      });
    },
    [places, on, pixelRatio],
  );
  return null;
}

/** The places to see layer: one switch in Layers, off by default. */
export function PlacesOverlay({ getMap, places, on }: { getMap: () => MapLibreMap | null; places: readonly SightPlace[] | null; on: boolean }) {
  useMap(
    getMap,
    (map) => {
      if (!places || places.length === 0) {
        if (map.getLayer(PLACES_LAYER)) map.setLayoutProperty(PLACES_LAYER, "visibility", "none");
        return;
      }
      setSource(map, PLACES_SOURCE_ID, placesGeoJson(places));
      if (!map.getLayer(PLACES_LAYER)) map.addLayer(placesLayer() as never, map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined);
      map.setLayoutProperty(PLACES_LAYER, "visibility", on ? "visible" : "none");
      const byId = new Map(places.map((p) => [p.id, p]));
      return tapCard(map, PLACES_LAYER, (id) => {
        const p = byId.get(id);
        if (!p) return null;
        return [p.name, `${categoryOf(p).one}.`, ...(p.hours ? [`Hours as mapped: ${p.hours}.`] : []), "From OpenStreetMap."];
      });
    },
    [places, on],
  );
  return null;
}
