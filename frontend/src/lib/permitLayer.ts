/**
 * DC permits (v0.9.1): DDOT's occupancy permits, which allow a road to be closed (or a bike lane blocked) some time in
 * their window. Stephen, 2026-10-19: "What those closures mean is that 'it could be closed some time in the next month
 * or so'. It's a useful layer for something where you'll be planning a group ride, but I wouldn't cancel a solo ride
 * because of it", "We should flag, but not necessarily stop anyone", "And turn the notices off", "off by default too".
 *
 * So the server never routes round a permit and never names one in the route's words, a spoken cue or the closure
 * check; the route's answer flags each near it (effect "possible", lib/closureMap.ts), and this one switch in Plan's
 * Layers, off by default and kept on this device, draws them, dashed, each with its card. Go never shows them.
 */
import { createElement as h, type ReactElement } from "react";
import { LayerSection } from "./layerSection.ts";

export const PERMITS_LABEL = "DC permits";
export const PERMITS_HINT =
  "Roads and bike lanes a DDOT permit allows closing some time in its window: worth checking for a group ride. Routes are not changed for them.";
export const PERMITS_PREF_KEY = "routemaker.permitsLayer";

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The switch as kept on this device; off when nothing is kept or storage is blocked (off by default). */
export function readPermitsLayer(store: Store | null = defaultStore()): boolean {
  try {
    return store?.getItem(PERMITS_PREF_KEY) === "on";
  } catch {
    return false;
  }
}

export function savePermitsLayer(on: boolean, store: Store | null = defaultStore()): void {
  try {
    store?.setItem(PERMITS_PREF_KEY, on ? "on" : "off");
  } catch {
    // Not kept: the switch still works for this visit.
  }
}

/** Whether the permits are drawn: the switch on, in Plan (Go never shows them). */
export function permitsShown(on: boolean, mode: "go" | "plan" | string): boolean {
  return on && mode === "plan";
}

/** The Map layers section: one switch, its hint inside. */
export function PermitsSection({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }): ReactElement {
  return h(
    LayerSection,
    { id: "permits", title: PERMITS_LABEL, headingId: "permits-heading", layers: [{ key: "permits", label: PERMITS_LABEL, on }], onLayers: (next) => onChange(next.permits) },
    h("p", { className: "hint", id: "permits-hint" }, PERMITS_HINT),
  );
}
