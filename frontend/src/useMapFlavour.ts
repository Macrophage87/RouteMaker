// The base map's flavour, kept in line with the theme, the ride, the light and tunnels (lib/mapFlavour.ts,
// lib/tunnelDark.ts; the owner, 2026-11-01: battery audit). Its own hook, so MapView only names it.
import { useEffect, useRef } from "react";
import { applyMapFlavour, mapFlavourFor, nextLightChange, type FlavourMap, type MapFlavour } from "./lib/mapFlavour.ts";
import { BASEMAP_SOURCE_ID } from "./lib/mapStyle.ts";
import { NO_TUNNEL, TUNNEL_NEAR_M, aheadOnLine, inTunnelAt, nearRoad, roadLayerIds, tunnelCheckWait, tunnelStep, type NearRoad, type TunnelState } from "./lib/tunnelDark.ts";
import type { LonLat } from "./lib/geo.ts";

const DARK_THEME = "(prefers-color-scheme: dark)";

/** Whether the page is in the dark theme now (the panels' own media query, styles.css). */
export function themeIsDark(): boolean {
  try {
    return typeof matchMedia === "function" && matchMedia(DARK_THEME).matches;
  } catch {
    return false;
  }
}

type RenderedRoad = { properties?: Record<string, unknown> | null; geometry: { type: string; coordinates: unknown } };

/** The map as the hook uses it: the change's parts, where it is, its load, and its rendered roads. */
export type FlavourHost = FlavourMap & {
  getCenter(): { lng: number; lat: number };
  getZoom(): number;
  project(at: LonLat): { x: number; y: number };
  queryRenderedFeatures(box: [[number, number], [number, number]], options: { layers: string[] }): RenderedRoad[];
  getStyle(): { layers: ReadonlyArray<{ id: string; "source-layer"?: string; source?: string }> };
  on(type: "load", listener: () => void): unknown;
  off(type: "load", listener: () => void): unknown;
};

/** The base map's roads rendered within `metres` of `at` (a box of that half-width on screen). */
function roadsNear(map: FlavourHost, at: LonLat, metres: number): NearRoad[] {
  const layers = roadLayerIds(map.getStyle().layers.filter((layer) => layer.source === BASEMAP_SOURCE_ID));
  if (layers.length === 0) return [];
  const perPx = (40_075_016.686 * Math.cos((at[1] * Math.PI) / 180)) / (512 * 2 ** map.getZoom());
  const r = Math.max(2, metres / perPx);
  const { x, y } = map.project(at);
  return map
    .queryRenderedFeatures(
      [
        [x - r, y - r],
        [x + r, y + r],
      ],
      { layers },
    )
    .map(nearRoad)
    .filter((road): road is NearRoad => road !== null);
}

/**
 * Keep the map's flavour: at load, when the theme changes, when a ride or Roam starts or ends (`onBike`), at the next
 * civil dawn or dusk while on the bike, and in and out of a tunnel (checked on the bike as a new fix comes, at most
 * every TUNNEL_CHECK_MS, at `rider()`'s spot and along its route ahead). `fix` is the rider's point, a new one with
 * each real fix. `opened` is the flavour the style was built in; `changed` hears each change made (the station icons
 * are drawn again for it).
 */
export function useMapFlavour(
  mapRef: { readonly current: FlavourHost | null },
  loaded: { readonly current: boolean },
  onBike: boolean,
  opened: MapFlavour,
  rider: () => { at: LonLat | null; line: readonly LonLat[] | null },
  fix: LonLat | null,
  changed?: (dark: boolean) => void,
): void {
  const shown = useRef<MapFlavour>(opened);
  // The tunnel check's door for a new fix, open on the bike only (set by the effect below).
  const fixCame = useRef<(() => void) | null>(null);
  const heard = useRef(changed);
  const where = useRef(rider);
  useEffect(() => {
    heard.current = changed;
    where.current = rider;
  });
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return undefined;
    let wake: number | undefined;
    let tunnel: TunnelState = NO_TUNNEL;
    const update = () => {
      window.clearTimeout(wake);
      if (!loaded.current) return;
      const centre = map.getCenter();
      const now = Date.now();
      const want = mapFlavourFor({ themeDark: themeIsDark(), onBike, now, at: [centre.lng, centre.lat], tunnel: tunnel.dark });
      const from = shown.current;
      applyMapFlavour(map, from, want, window.location.origin);
      shown.current = want;
      if (from !== want) heard.current?.(want === "dark");
      // On the bike the light decides too: look again at the next dawn or dusk (a second after, past the edge).
      const next = onBike ? nextLightChange(now, centre.lat, centre.lng) : null;
      if (next !== null) wake = window.setTimeout(update, Math.max(1000, next - now + 1000));
    };
    // The tunnel check, on the bike only, as a new fix comes and at most every TUNNEL_CHECK_MS (a fix sooner waits for
    // it, then the latest fix is read): the roads at the last fix and just ahead. No fix, no check (battery audit).
    let lastCheck: number | null = null;
    let waiting: number | undefined;
    const checkTunnel = () => {
      waiting = undefined;
      lastCheck = Date.now();
      const { at, line } = where.current();
      if (!at || !loaded.current) return;
      const ahead = aheadOnLine(line, at);
      const seen = [at, ...(ahead ? [ahead] : [])].some((point) => inTunnelAt(roadsNear(map, point, TUNNEL_NEAR_M), point));
      const next = tunnelStep(tunnel, seen, Date.now(), at);
      const turned = next.dark !== tunnel.dark;
      tunnel = next;
      if (turned) update();
    };
    fixCame.current = onBike
      ? () => {
          const wait = tunnelCheckWait(lastCheck, waiting !== undefined, Date.now());
          if (wait === null) return;
          if (wait === 0) checkTunnel();
          else waiting = window.setTimeout(checkTunnel, wait);
        }
      : null;
    let query: MediaQueryList | null = null;
    try {
      query = typeof matchMedia === "function" ? matchMedia(DARK_THEME) : null;
    } catch {
      query = null;
    }
    query?.addEventListener?.("change", update);
    map.on("load", update);
    update();
    return () => {
      window.clearTimeout(wake);
      window.clearTimeout(waiting);
      fixCame.current = null;
      query?.removeEventListener?.("change", update);
      map.off("load", update);
    };
  }, [mapRef, loaded, onBike]);
  useEffect(() => {
    if (fix) fixCame.current?.();
  }, [fix]);
}
