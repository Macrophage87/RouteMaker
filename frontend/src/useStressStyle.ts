import { useSyncExternalStore } from "react";
import { styleKey, subscribePalette } from "./stressStyle.js";

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
