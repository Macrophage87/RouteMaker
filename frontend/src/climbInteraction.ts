/**
 * Pressing a climb, its summit marker or its line: the climb card (lib/climbCard.ts), with the climb's
 * figures, its elevation profile and "Ride this climb" (the owner, 2026-10-12).
 *
 * Unlike the water card, a press on a climb is the climb's, not also a new point: MapView's click asks
 * `climbAt` first (after a station, which keeps its own card) and opens the card instead of placing a
 * point, in Plan and in Go alike. The summit marker wins over the route line drawn over it; the climb's
 * own line gives way to the route line, so a press on a route that rides a climb still adds a stop. The
 * click after the card is open only closes it, as a station card's does. It also closes on Escape (the
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

  const close = (focusBack = false) => {
    const was = popup;
    popup = null;
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

  /** The climb under a press: its summit marker, or (unless the route line is there too) its line. */
  const climbAt = (point: { x: number; y: number }, onRouteLine: boolean): Climb | null => {
    if (!options.visible()) return null;
    const { x, y } = point;
    const marker = query(
      [
        [x - TAP_SLOP, y - TAP_SLOP],
        [x + TAP_SLOP, y + TAP_SLOP],
      ],
      CLIMBS_MARKER_LAYER,
    );
    if (marker || onRouteLine) return marker;
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
    if (focus) {
      map.easeTo({ center: [c.lon, c.lat] });
      // After React has drawn it: the card itself takes the focus, so its name is said first.
      window.setTimeout(() => (container.querySelector(".climb-popup") as HTMLElement | null)?.focus(), 0);
    }
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
    detach() {
      close();
      window.removeEventListener("keydown", onKey);
    },
  };
}
