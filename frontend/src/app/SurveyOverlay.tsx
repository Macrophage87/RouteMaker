// The Survey spots layer on the map (lib/surveySpots.ts): an orange "!" per spot (a quest marker) the rider has not answered, over the
// roads. A press on one opens its card (SurveyCard.tsx), never a point or the destination (app/mapOverlay.ts
// cardLayer). App decides when it shows (its switch in Layers) and loads the spots the first time it is on.
import { useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { cardLayer, setSource, useMap } from "./mapOverlay.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import { loadSurveySpots, surveyGeoJson, surveyIcon, surveyLayer, SURVEY_ICON_ID, SURVEY_LAYER, SURVEY_SOURCE, type SurveySpot } from "../lib/surveySpots.ts";

export type SurveyStatus = "loading" | "ready" | "unavailable";

/** The spots, loaded the first time `on` is true (or `need` asks, as a ride's end does); `drop` takes answered ones out. */
export function useSurveySpots(on: boolean, origin: string, account: string | null): { spots: SurveySpot[] | null; status: SurveyStatus; drop: (id: string) => void } {
  const [spots, setSpots] = useState<SurveySpot[] | null>(null);
  const [status, setStatus] = useState<SurveyStatus>("loading");
  const asked = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    // Asked again when the account changes: the list leaves out the rider's answered spots.
    if (!on || asked.current === account) return;
    asked.current = account;
    void loadSurveySpots(origin).then((found) => {
      if (!found) asked.current = undefined;
      setSpots(found);
      setStatus(found === null ? "unavailable" : "ready");
    });
  }, [on, origin, account]);
  const drop = (id: string) => setSpots((list) => (list ? list.filter((s) => s.id !== id) : list));
  return { spots, status, drop };
}

export function SurveyOverlay({ getMap, on, spots, onPick }: { getMap: () => MapLibreMap | null; on: boolean; spots: readonly SurveySpot[] | null; onPick: (spot: SurveySpot) => void }) {
  useMap(
    getMap,
    (map) => {
      if (!on || !spots) {
        if (map.getLayer(SURVEY_LAYER)) map.setLayoutProperty(SURVEY_LAYER, "visibility", "none");
        return;
      }
      if (!map.hasImage(SURVEY_ICON_ID)) {
        const { pixelRatio, ...image } = surveyIcon(Math.min(Math.max(globalThis.devicePixelRatio || 1, 1), 3));
        map.addImage(SURVEY_ICON_ID, image, { pixelRatio });
      }
      setSource(map, SURVEY_SOURCE, surveyGeoJson(spots));
      if (!map.getLayer(SURVEY_LAYER)) map.addLayer(surveyLayer() as never, map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined);
      map.setLayoutProperty(SURVEY_LAYER, "visibility", "visible");
      const byId = new Map(spots.map((s) => [s.id, s]));
      return cardLayer(map, SURVEY_LAYER, (id) => {
        const spot = byId.get(id);
        if (spot) onPick(spot);
      });
    },
    [on, spots, onPick],
  );
  return null;
}
