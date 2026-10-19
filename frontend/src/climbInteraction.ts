/**
 * Pressing a climb, its summit marker or its line: the climb card (lib/climbCard.ts), with the climb's
 * figures, its elevation profile and "Ride this climb" (the owner, 2026-10-12).
 *
 * Unlike the water card, a press on a climb is the climb's, not also a new point: MapView's click asks
 * `climbAt` first (after a station and a water or restroom icon, which keep their own cards) and opens the
 * card instead of placing a point. Its summit marker and its dashed line open it, in Plan as in Go (the owner,
 * 2026-10-19: "You should also be able to select and click on climbs too"), except that in Plan a press on the
 * planned route's own line stays the route's (a via); in Go it is a feature card, never the destination. The click after the card is open only closes it, as a station card's does. It also closes on Escape (the
 * focus going back where it was), and does nothing while the layer is off. The road panel's "Climb
 * details" opens it from the keyboard, with the focus in it (`openCard(c, true)`).
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, PointLike } from "maplibre-gl";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { CLIMBS_LINE_LAYER, CLIMBS_MARKER_LAYER, type Climb } from "./lib/climbs.ts";
import { ClimbCardView, fetchClimbProfile, type ProfileState } from "./lib/climbCard.ts";

export interface ClimbInteractionOptions {
  visible(): boolean;
  climb(id: string): Climb | undefined;
  /** "Ride this climb": App puts it in the plan (Plan) or plans to its top (Go). */
  onRide(c: Climb): void;
}

/** Pixels around a press that still count as on the marker, and on the dashed line. */
const TAP_SLOP = 6;
const LINE_SLOP = 8;

/** The profiles asked for this visit (they do not change); an error is not kept, so a later card asks again. */
const profiles = new Map<string, ProfileState | Promise<ProfileState>>();

function profileFor(id: string): ProfileState | Promise<ProfileState> {
  const kept = profiles.get(id);
  if (kept) return kept;
  const asked = fetchClimbProfile(id).then((state) => {
    if (state.kind === "error") profiles.delete(id);
    else profiles.set(id, state);
    return state;
  });
  profiles.set(id, asked);
  return asked;
}

export function attachClimbInteraction(map: MapLibreMap, options: ClimbInteractionOptions) {
  let popup: maplibregl.Popup | null = null;
  let root: Root | null = null;
  let returnTo: Element | null = null;
  let serial = 0;
  /** The id of the climb whose card is open, or null. */
  let shownId: string | null = null;

  const close = (focusBack = false) => {
    const was = popup;
    popup = null;
    shownId = null;
    if (root) {
      const r = root;
      root = null;
      // Not inside React's own render: the popup may be closed from a click React is handling.
      queueMicrotask(() => r.unmount());
    }
    was?.remove();
    if (focusBack && was) {
      const back = returnTo;
      const target = back instanceof HTMLElement && back.isConnected && back !== document.body ? back : map.getCanvas();
      target.focus();
    }
    returnTo = null;
  };

  const query = (box: [PointLike, PointLike], layer: string): Climb | null => {
    if (!map.getLayer(layer)) return null;
    const feature = map.queryRenderedFeatures(box, { layers: [layer] })[0];
    const id = (feature?.properties as { id?: string } | undefined)?.id;
    return (id && options.climb(id)) || null;
  };

  /** The climb under a press: its summit marker, or with `withLine` (Go) its dashed line too. */
  const climbAt = (point: { x: number; y: number }, withLine: boolean): Climb | null => {
    if (!options.visible()) return null;
    const { x, y } = point;
    const marker = query(
      [
        [x - TAP_SLOP, y - TAP_SLOP],
        [x + TAP_SLOP, y + TAP_SLOP],
      ],
      CLIMBS_MARKER_LAYER,
    );
    if (marker || !withLine) return marker;
    return query(
      [
        [x - LINE_SLOP, y - LINE_SLOP],
        [x + LINE_SLOP, y + LINE_SLOP],
      ],
      CLIMBS_LINE_LAYER,
    );
  };

  const openCard = (c: Climb, focus = false) => {
    close();
    shownId = c.id;
    serial += 1;
    const uid = `climb-card-${serial}`;
    returnTo = document.activeElement;
    const container = document.createElement("div");
    container.addEventListener("keydown", (key) => {
      if (key.key !== "Escape") return;
      key.preventDefault();
      key.stopPropagation();
      close(true);
    });
    const thisRoot = createRoot(container);
    root = thisRoot;
    const draw = (state: ProfileState) => {
      if (root !== thisRoot) return;
      thisRoot.render(
        createElement(ClimbCardView, {
          climb: c,
          state,
          uid,
          focusOnMount: focus,
          onRide: () => {
            close();
            options.onRide(c);
          },
        }),
      );
    };
    const kept = profileFor(c.id);
    if (kept instanceof Promise) {
      draw({ kind: "loading" });
      void kept.then(draw);
    } else draw(kept);
    // Not closed by MapLibre on a map click: MapView's click closes it, so that the same click does not
    // also add a point (as a station card).
    popup = new maplibregl.Popup({ className: "rail-popup climb-card", offset: 12, focusAfterOpen: false, closeOnClick: false, maxWidth: "300px" })
      .setLngLat([c.lon, c.lat])
      .setDOMContent(container)
      .addTo(map);
    popup.on("close", () => {
      if (root === thisRoot) close();
    });
    // With `focus` (the road panel's "Climb details") the card takes the focus itself once React has
    // mounted it (ClimbCardView's focusOnMount), so its name is said first.
    if (focus) map.easeTo({ center: [c.lon, c.lat] });
  };

  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape" && popup) close();
  };
  window.addEventListener("keydown", onKey);
  return {
    climbAt,
    openCard,
    close: () => close(),
    open: () => popup !== null,
    /** The id of the climb whose card is open, or null. */
    shown: () => (popup ? shownId : null),
    /** Whether a Go press at `point` is on a shown climb, its marker or its line (lib/mapGlue.ts featureCardPress). */
    hits: (point: { x: number; y: number }) => climbAt(point, true) !== null,
    detach() {
      close();
      window.removeEventListener("keydown", onKey);
    },
  };
}
