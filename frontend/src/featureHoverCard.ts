/**
 * The hover card of a climb or a mountain-bike trail (the owner, 2026-10-20: "Basically they would work sort of like how
 * our metros do now." and "You'd see trail name, then the difficulty rating and what it's based on with an elevation
 * map."): as a station's hover card (railInteraction.ts), a small card at the mouse with the name and a line about it,
 * which the pointer goes through, and a click opens the whole card (the climb card, the trail's road panel). Its
 * elevation profile is asked for once the mouse has rested on the feature a moment, and kept for the next hover.
 *
 * Mouse only: a tap opens the whole card at once, and the keyboard reaches both cards as before. The card is out of
 * the accessibility tree: the whole card says all of it, in words.
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { LonLat } from "./lib/geo.ts";
import type { HoverWords } from "./lib/featureHover.ts";

/** How long the mouse rests on a feature before its profile is asked for: a pass across the map asks for nothing. */
export const PROFILE_DWELL_MS = 350;

export interface FeatureHoverCard {
  /** The card for `words` at `at`, built only when the feature changes; `chart` gives its profile, or null for none. */
  show(words: HoverWords, at: LonLat, chart: () => Promise<ReactElement | null>): void;
  hide(): void;
}

export function attachFeatureHover(map: MapLibreMap): FeatureHoverCard {
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "rail-popup rail-hover feature-hover", offset: 12, maxWidth: "300px" });
  let shown = "";
  let timer = 0;
  let root: Root | null = null;
  // Counts the cards shown, so a profile that arrives after its card has gone is dropped.
  let generation = 0;

  const hide = () => {
    if (shown === "") return;
    shown = "";
    generation += 1;
    window.clearTimeout(timer);
    const gone = root;
    root = null;
    // Not inside a React render: the hover runs from a map event.
    gone?.unmount();
    popup.remove();
  };

  const show: FeatureHoverCard["show"] = (words, at, chart) => {
    if (words.key === shown) return;
    hide();
    shown = words.key;
    const body = document.createElement("div");
    body.className = "feature-hover-card";
    body.setAttribute("aria-hidden", "true");
    const title = document.createElement("strong");
    title.className = "station-name";
    title.textContent = words.title;
    const detail = document.createElement("p");
    detail.className = "feature-hover-detail";
    detail.textContent = words.detail;
    const profile = document.createElement("div");
    profile.className = "feature-hover-profile";
    body.append(title, detail, profile);
    popup.setLngLat(at).setDOMContent(body).addTo(map);
    const mine = ++generation;
    timer = window.setTimeout(() => {
      chart().then(
        (element) => {
          if (mine !== generation || element === null) return;
          root = createRoot(profile);
          root.render(element);
        },
        () => undefined,
      );
    }, PROFILE_DWELL_MS);
  };

  return { show, hide };
}
