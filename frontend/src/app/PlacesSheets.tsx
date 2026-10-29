// v0.7.0's place sheets: Go's Repair and Sights (behind the More chip; the owner, 2026-10-14: "Make sure that go
// stays clean, but they can find it there. Plan can have more complexity"), and Plan's Places to see. Each list
// is lettered as the map's markers are (lib/letteredPlaces.ts); a Go row has Ride here first, as Eat's and Water's rows do,
// and Show on map, which opens the place's card on the map (what's there, its website: lib/stopCard.ts). App.tsx keeps
// the state; the lists are lib/repair.ts's and lib/places.ts's.
import { useId, type ReactNode } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { setSource, stopCard, useMap } from "./mapOverlay.ts";
import { foodWords, repairWords, sightWords } from "../lib/stopWords.ts";
import type { StopActionFor } from "../lib/stopCard.ts";
import { Icon } from "../Icon.tsx";
import { SheetFrame } from "../Sidebar.tsx";
import { placeLetter, SHOW_ALL_ON_MAP } from "../lib/letteredPlaces.ts";
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
import { hoursText } from "../lib/openingHours.ts";

/**
 * A Go place row's buttons, as Eat's and Water's (the 2026-10-29 review: one row pattern in Go): Ride here first and
 * filled, the one main action; then Show on map, which opens the place's card (what's there, its website).
 */
function PlaceActions({ name, index, describedBy, onRide, onCard }: { name: string; index: number; describedBy?: string; onRide: () => void; onCard: () => void }) {
  return (
    <span className="actions">
      <button type="button" className="ride-here" aria-label={t("Ride here: {place}", { place: name })} aria-describedby={describedBy} onClick={onRide}>
        {t("Ride here")}
      </button>
      <button type="button" className="secondary" aria-label={t("Show on map: {place}, marker {letter}", { place: name, letter: placeLetter(index) })} onClick={onCard}>
        {t("Show on map")}
      </button>
    </span>
  );
}

/** Go's Repair: the nearest repair stands and bike shops, lettered; Ride here, or Show on map for its card. */
export function RepairSheet({
  nav,
  status,
  items,
  at,
  onPick,
  onRide,
}: {
  nav: SheetNav;
  status: string;
  items: readonly RepairNearby[] | null;
  at: Date;
  onPick: (item: RepairNearby) => void;
  onRide: (item: RepairNearby) => void;
}) {
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
                <span>
                  <Icon name={item.place.kind === "stand" ? "wrench" : "shop"} size={18} />{" "}
                  {/* Named, not lettered, on the map (#628): the letter is heard, as in the other place lists. */}
                  <strong>
                    <span className="visually-hidden">{placeLetter(i)}. </span>
                    {repairTitle(item.place)}
                  </strong>{" "}
                  {repairHowFar(item)}. <span id={`${rowId}-${i}`}>{repairDetails(item.place, at).join(" ")}</span>
                </span>
                <PlaceActions name={repairTitle(item.place)} index={i} describedBy={`${rowId}-${i}`} onRide={() => onRide(item)} onCard={() => onPick(item)} />
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
      {/* The map's marker shows the name (Stephen 2026-10-29: "Named, not lettered"); the letter, its key's, is heard. */}
      <strong>
        <span className="visually-hidden">{placeLetter(index)}. </span>
        {result.place.name}
      </strong>{" "}
      {category.one}. {sightHowFar(result)}.{children}
    </span>
  );
}

/** Go's Places to see: the nearest five, no filters; Ride here, or Show on map for its card. */
export function SightsList({ items, onPick, onRide }: { items: readonly SightResult[]; onPick: (result: SightResult) => void; onRide: (result: SightResult) => void }) {
  return (
    <ol role="list" className="nearest-list sights-list" aria-label={t("Places to see")}>
      {items.map((r, i) => (
        <li key={r.place.id}>
          <SightRow result={r} index={i} />
          <PlaceActions name={r.place.name} index={i} onRide={() => onRide(r)} onCard={() => onPick(r)} />
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
  /** Show all on map (Stephen 2026-10-29): every place listed, named on the map, framed together. */
  onShowAll?: () => void;
  onAddStop: (result: SightResult) => void;
  /** Go: a row's Show on map, the place's card on the map. */
  onGoPick: (result: SightResult) => void;
  /** Go: a row's Ride here, the place as the destination. */
  onGoRide: (result: SightResult) => void;
}

/** Places to see: Plan's with filters, hours and website, Go's the nearest five, one tap each. One name in both, as
 * their chips say it (P12: Go's was "Sights"). */
export function PlacesSheet(props: PlacesSheetProps) {
  const { nav, go, status, items, total, onMore, filter, onFilter, canAddStop, onShow, onShowAll, onAddStop, onGoPick, onGoRide } = props;
  // The hours in words for now ("Open now · closes 5 PM": lib/openingHours.ts).
  const now = new Date();
  return (
    <SheetFrame id="sheet-places" title={SHEET_TITLES.places} open={nav.view === "places"} onBack={nav.back} backLabel={nav.backLabel("places")}>
      {!go && (
        <label className="places-filter">
          {t("Show")}{" "}
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
      {items && items.length > 0 && go && <SightsList items={items} onPick={onGoPick} onRide={onGoRide} />}
      {items && items.length > 1 && !go && onShowAll && (
        <button type="button" className="secondary show-all" onClick={onShowAll}>
          {SHOW_ALL_ON_MAP}
        </button>
      )}
      {items && items.length > 0 && !go && (
        <ol role="list" className="nearest-list places-list" aria-label={t("Places to see")}>
          {items.map((r, i) => (
            <li key={r.place.id}>
              <SightRow result={r} index={i}>
                {r.place.hours ? ` ${hoursText(r.place.hours, now)}.` : ""}
              </SightRow>
              <span className="actions">
                <button type="button" className="secondary" aria-label={t("Show on map: {place}, marker {letter}", { place: r.place.name, letter: placeLetter(i) })} onClick={() => onShow(r)}>
                  {t("Show on map")}
                </button>
                {canAddStop && (
                  <button type="button" className="secondary" aria-label={t("Add as stop: {place}", { place: r.place.name })} onClick={() => onAddStop(r)}>
                    {t("Add as stop")}
                  </button>
                )}
                {r.place.website && (
                  <a className="food-web" href={r.place.website} target="_blank" rel="noopener noreferrer" aria-label={t("Website: {place} (opens in a new tab)", { place: r.place.name })}>
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
          {t("Show {count} more", { count: Math.min(PLACES_PAGE, total - items.length) })}
        </button>
      )}
      {items && items.length > 0 && <p className="hint">{PLACES_NOTE}</p>}
    </SheetFrame>
  );
}

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
