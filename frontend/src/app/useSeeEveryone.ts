/**
 * See everyone's state for App (lib/seeEveryone.ts has the rules): the view that frames the rider and every other
 * rider's dot while it is on.
 */
import { useCallback, useEffect, useReducer, useRef } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { LonLat } from "../lib/geo.ts";
import { frameAround, rideOpenPadding } from "../lib/detourSearch.ts";
import { dotsKey, dotsOffScreen, everyoneFrame, everyoneStep, openBox } from "../lib/seeEveryone.ts";

/** How often the view checks the rider is still in it. */
export const RIDER_CHECK_MS = 3000;

export interface SeeEveryone {
  /** The button shows: other riders' dots are on the map (Stephen 2026-10-30: "Always, when sharing"). */
  shown: boolean;
  on: boolean;
  /** On: frames everyone (the map stops following). Off: back to the rider. */
  toggle: () => void;
  /** A move by hand: the view ends there (the idle recentre brings the rider back). */
  stop: () => void;
}

interface Options {
  getMap: () => MapLibreMap | null;
  /** The other riders' dots shown on the map now. */
  dots: readonly LonLat[];
  /** The rider's own position, where known. */
  rider: () => LonLat | null;
  /** A ride or Roam is under way. */
  active: boolean;
  follow: boolean;
  /** The map stops following the rider (the view is on). */
  onUnfollow: () => void;
  /** Back to following the rider at the ride's own zoom. */
  onBackToRider: () => void;
}

/** The map the ride's card, bottom panel and side buttons leave open, in the map's own pixels. */
function openPadding(map: MapLibreMap) {
  const box = (selector: string) => document.querySelector(selector)?.getBoundingClientRect() ?? null;
  return rideOpenPadding(map.getContainer().getBoundingClientRect(), box(".ride-middle"), box(".ride-rail"));
}

export function useSeeEveryone({ getMap, dots, rider, active, follow, onUnfollow, onBackToRider }: Options): SeeEveryone {
  const [on, dispatch] = useReducer(everyoneStep, false);
  const key = dotsKey(dots);
  const dotsNow = useRef(dots);
  dotsNow.current = dots;
  const any = active && dots.length > 0;

  const frame = useCallback(
    (instant: boolean) => {
      const map = getMap();
      if (!map || dotsNow.current.length === 0) return;
      const still = instant || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      map.fitBounds(frameAround(everyoneFrame(dotsNow.current, rider())), { padding: openPadding(map), bearing: map.getBearing(), maxZoom: 17, duration: still ? 0 : 600 });
    },
    [getMap, rider],
  );

  // Kept framing everyone as the dots move; ended with the ride, with the last dot gone, or once following again.
  useEffect(() => {
    if (!on) return;
    if (!any) {
      dispatch({ kind: "dots-gone" });
      if (active) onBackToRider();
      return;
    }
    frame(false);
    // Each new set of places frames again; the callbacks are App's own.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, any, key]);
  // The rider rides on while the others wait (a regroup): framed again once the rider leaves the open map.
  useEffect(() => {
    if (!on) return;
    const id = window.setInterval(() => {
      const map = getMap();
      const me = rider();
      if (!map || !me) return;
      const { width, height } = map.getContainer().getBoundingClientRect();
      if (dotsOffScreen([me], (at) => map.project(at), openBox(width, height, openPadding(map)))) frame(false);
    }, RIDER_CHECK_MS);
    // A turned phone or a panel that changed the map's size: framed again in the new shape.
    const map = getMap();
    const refit = () => frame(true);
    map?.on("resize", refit);
    return () => {
      window.clearInterval(id);
      map?.off("resize", refit);
    };
  }, [on, getMap, rider, frame]);
  // Following again (Where am I?, the button, the idle recentre): the view ends (lib/seeEveryone.ts everyoneStep).
  useEffect(() => {
    if (follow) dispatch({ kind: "following" });
  }, [follow]);

  const toggle = useCallback(() => {
    dispatch({ kind: "press" });
    if (on) onBackToRider();
    else onUnfollow();
  }, [on, onUnfollow, onBackToRider]);
  const stop = useCallback(() => dispatch({ kind: "hand-move" }), []);

  return { shown: any, on, toggle, stop };
}
