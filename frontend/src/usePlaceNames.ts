/**
 * Human names for the plan's points (owner request of 2026-09-27: "use a
 * human understandable place name for start and end ... Most people don't
 * work in latitude and longitude").
 *
 * Each point is named once, after it settles - a dragged marker is named
 * where it is dropped, not along the way - through the page's one geocoding
 * gate. The names are not written into the link: the fragment stays points
 * and ride type, and a link opened elsewhere names its points afresh.
 */
import { useEffect, useRef, useState } from "react";
import { GeoGate, PlaceNamer, nameSender } from "./lib/geocode.ts";
import type { LonLat } from "./lib/geo.ts";

export function usePlaceNames(points: readonly LonLat[]) {
  const gate = useRef<GeoGate | null>(null);
  if (gate.current === null) gate.current = new GeoGate();
  const [, setVersion] = useState(0);
  const namer = useRef<PlaceNamer | null>(null);
  if (namer.current === null) {
    const g = gate.current;
    namer.current = new PlaceNamer({
      send: nameSender(g),
      onChange: () => setVersion((v) => v + 1),
    });
  }
  useEffect(() => {
    namer.current?.want(points);
  }, [points]);
  return { gate: gate.current, namer: namer.current };
}
