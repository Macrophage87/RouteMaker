import { useSyncExternalStore } from "react";
import { highStressLanesOn, mtbTrailsOn, styleKey, subscribeHighStressLanes, subscribeMtbTrails, subscribePalette } from "./stressStyle.js";

/**
 * Re-render the component when the stress colours or their strength change:
 * the rider flips the accessibility switch, or the system's request for more
 * contrast changes with the page open (stressStyle.js, setAccessibility and
 * watchContrast). A component that draws the stress colours calls this, then
 * reads currentTiers(): without it the legend and the stress bar would keep
 * the colours they were drawn in. Returns the style's key.
 */
export function useStressStyle(): string {
  return useSyncExternalStore(subscribePalette, styleKey, styleKey);
}

/**
 * Re-render the component when the "Show bike lanes on high-stress roads"
 * switch changes (OWNER-DECISIONS 275); returns whether it is on. A component
 * that draws the facility legend, the facility bar or the route description
 * calls this.
 */
export function useHighStressLanes(): boolean {
  return useSyncExternalStore(subscribeHighStressLanes, highStressLanesOn, highStressLanesOn);
}

/**
 * Re-render the component when the "Mountain-bike trails" map layer is turned
 * on or off (OWNER-DECISIONS 454); returns whether it is on. The Map layers
 * sheet and the legend call this.
 */
export function useMtbTrails(): boolean {
  return useSyncExternalStore(subscribeMtbTrails, mtbTrailsOn, mtbTrailsOn);
}
