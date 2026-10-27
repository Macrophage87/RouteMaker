// v0.7.0's place sheets: Go's Repair and Sights (behind the More chip; the owner, 2026-10-14: "Make sure that go
// stays clean, but they can find it there. Plan can have more complexity"), and Plan's Places to see. Each list
// is lettered as the map's markers are (lib/letteredPlaces.ts); a Go row's one button opens the place's card on the
// map (what's there, its website, Route here or Add as stop: lib/stopCard.ts), never a route by itself. App.tsx keeps the state; the lists are lib/repair.ts's and lib/places.ts's.
import { useId, type ReactNode } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { setSource, stopCard, useMap } from "./mapOverlay.ts";
import { foodWords, repairWords, sightWords } from "../lib/stopWords.ts";
import type { StopActionFor } from "../lib/stopCard.ts";
import { Icon } from "../Icon.tsx";
import { SheetFrame } from "../Sidebar.tsx";
import { placeLetter } from "../lib/letteredPlaces.ts";
import {
  REPAIR_ICON_ID,
  REPAIR_LAYER,
  REPAIR_NOTE,
  REPAIR_SOURCE_ID,
  repairDetails,
  repairGeoJson,
  repairHowFar,
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
import { FOOD_LAYER, FOOD_SOURCE_ID, foodGeoJson, foodLayer, type FoodResult } from "../lib/food.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import { SHEET_TITLES, type PanelView } from "../lib/sidebar.ts";
import type { SheetNav } from "./Sheets.tsx";
import { t } from "../lib/i18n.ts";

/** Go's Repair: the nearest repair stands and bike shops, lettered; a row opens its card. */
export function RepairSheet({ nav, status, items, at, onPick }: { nav: SheetNav; status: string; items: readonly RepairNearby[] | null; at: Date; onPick: (item: RepairNearby) => void }) {
  const rowId = useId();
  return (
    <SheetFrame id="sheet-repair" title={SHEET_TITLES.repair} open={nav.view === "repair"} onBack={nav.back} backLabel={nav.backLabel("repair")}>
      <p className="hint repair-status" role="status">
        {status}
      </p>
      {items && items.length > 0 && (
        <>
          <ol role="list" className="nearest-list repair-list" aria-label={t("Repair stands and bike shops")}>
            {items.map((item, i) => (
              <li key={item.place.id}>
                {/* Named by the place and how far; its details are its description (review F13), not repeated in the name. */}
                <button
                  type="button"
                  className="secondary place-row"
                  onClick={() => onPick(item)}
                  aria-label={`${placeLetter(i)}: ${repairTitle(item.place)}, ${repairHowFar(item)}`}
                  aria-describedby={`${rowId}-${i}`}
                >
                  <Icon name={item.place.kind === "stand" ? "wrench" : "shop"} size={18} />
                  <span>
                    <strong>
                      {placeLetter(i)}. {repairTitle(item.place)}
                    </strong>{" "}
                    {repairHowFar(item)}. <span id={`${rowId}-${i}`}>{repairDetails(item.place, at).join(" ")}</span>
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

/** Go's Sights: the nearest five, no filters; a row opens its card. */
export function SightsList({ items, onPick }: { items: readonly SightResult[]; onPick: (result: SightResult) => void }) {
  return (
    <ol role="list" className="nearest-list sights-list" aria-label={t("Places to see")}>
      {items.map((r, i) => (
        <li key={r.place.id}>
          <button type="button" className="secondary place-row" onClick={() => onPick(r)} aria-label={`${placeLetter(i)}: ${sightText(r)}`}>
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
  /** Go: a row's one tap, the place's card on the map. */
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
            <option value="all">{t("All places to see")}</option>
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
      {items && items.length > 0 && go && <SightsList items={items} onPick={onGoPick} />}
      {items && items.length > 0 && !go && (
        <ol role="list" className="nearest-list places-list" aria-label={t("Places to see")}>
          {items.map((r, i) => (
            <li key={r.place.id}>
              <SightRow result={r} index={i}>
                {r.place.hours ? ` Hours: ${r.place.hours}.` : ""}
              </SightRow>
              <span className="actions">
                <button type="button" className="secondary" aria-label={`Show on map: ${r.place.name}, marker ${placeLetter(i)}`} onClick={() => onShow(r)}>
                  {t("Show on map")}
                </button>
                {canAddStop && (
                  <button type="button" className="secondary" aria-label={`Add as stop: ${r.place.name}`} onClick={() => onAddStop(r)}>
                    {t("Add as stop")}
                  </button>
                )}
                {r.place.website && (
                  <a className="food-web" href={r.place.website} target="_blank" rel="noopener noreferrer" aria-label={`Website: ${r.place.name} (opens in a new tab)`}>
                    {t("Website")}
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
export function RepairStandsOverlay({ getMap, places, on, pixelRatio, actionFor }: { getMap: () => MapLibreMap | null; places: readonly RepairPlace[] | null; on: boolean; pixelRatio: number; actionFor: StopActionFor }) {
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
      return stopCard(map, REPAIR_LAYER, (id) => {
        const p = byId.get(id);
        return p ? { point: [p.lon, p.lat], words: repairWords(p, new Date()) } : null;
      }, actionFor);
    },
    [places, on, pixelRatio, actionFor],
  );
  return null;
}

/** The places to see layer: one switch in Layers, off by default. */
export function PlacesOverlay({ getMap, places, on, actionFor }: { getMap: () => MapLibreMap | null; places: readonly SightPlace[] | null; on: boolean; actionFor: StopActionFor }) {
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
      return stopCard(map, PLACES_LAYER, (id) => {
        const p = byId.get(id);
        return p ? { point: [p.lon, p.lat], words: sightWords(p, new Date()) } : null;
      }, actionFor);
    },
    [places, on, actionFor],
  );
  return null;
}

/** Every food place a search found, as dots under the lettered pins, while the Food sheet is open. */
export function FoodOverlay({ getMap, results, on, actionFor }: { getMap: () => MapLibreMap | null; results: readonly FoodResult[] | null; on: boolean; actionFor: StopActionFor }) {
  useMap(
    getMap,
    (map) => {
      if (!on || !results || results.length === 0) {
        if (map.getLayer(FOOD_LAYER)) map.setLayoutProperty(FOOD_LAYER, "visibility", "none");
        return;
      }
      setSource(map, FOOD_SOURCE_ID, foodGeoJson(results));
      if (!map.getLayer(FOOD_LAYER)) map.addLayer(foodLayer() as never, map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined);
      map.setLayoutProperty(FOOD_LAYER, "visibility", "visible");
      const byId = new Map(results.map((r) => [r.place.id, r]));
      return stopCard(map, FOOD_LAYER, (id) => {
        const r = byId.get(id);
        return r ? { point: [r.place.lon, r.place.lat], words: foodWords(r, new Date()) } : null;
      }, actionFor);
    },
    [results, on, actionFor],
  );
  return null;
}
