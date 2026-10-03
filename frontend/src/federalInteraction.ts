/**
 * Tapping or clicking a shaded federal area: a small card with the area's
 * name, its managing agency where the source names one, the kind, and the one
 * line "Federal land - permit rules may differ (information, not legal advice)".
 *
 * The card is information beside the map's own click, not instead of it: the
 * click still goes on to place a point as it always does (MapView's click),
 * because the planner's tap must keep meaning "put a point here". It closes on
 * the next map click, on its own button, and on Escape. It does nothing while
 * the overlay is off, so it is silent outside a Mass Ride, and it holds back
 * while another card (a via's Remove, a station) is open.
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import { FEDERAL_TINT_LAYER, federalCard, type FederalKind } from "./lib/federalLand.ts";

export interface FederalInteractionOptions {
  /** Whether the overlay is on the map now. */
  visible(): boolean;
  /** Another popup is open; this one stays out of its way. */
  otherPopupOpen(): boolean;
}

/** The popup's contents, as DOM (a test builds it too). */
export function federalCardElement(props: { kind: FederalKind; name: string; agency?: string }): HTMLElement {
  const card = federalCard(props);
  const root = document.createElement("div");
  root.className = "federal-popup";
  const title = document.createElement("strong");
  title.className = "federal-name";
  title.textContent = card.title;
  root.append(title);
  const kind = document.createElement("p");
  kind.className = "federal-kind-line";
  kind.textContent = card.kind;
  root.append(kind);
  if (card.agency) {
    const agency = document.createElement("p");
    agency.className = "federal-agency";
    agency.textContent = `Managed by: ${card.agency}`;
    root.append(agency);
  }
  const note = document.createElement("p");
  note.className = "federal-note";
  note.textContent = `${card.note}.`;
  root.append(note);
  return root;
}

export function attachFederalInteraction(map: MapLibreMap, options: FederalInteractionOptions) {
  let popup: maplibregl.Popup | null = null;
  const close = () => {
    popup?.remove();
    popup = null;
  };
  const onClick = (event: maplibregl.MapMouseEvent) => {
    close();
    if (!options.visible() || options.otherPopupOpen() || !map.getLayer(FEDERAL_TINT_LAYER)) return;
    if (event.originalEvent.target !== map.getCanvas()) return;
    const feature = map.queryRenderedFeatures(event.point, { layers: [FEDERAL_TINT_LAYER] })[0];
    const props = feature?.properties as { kind?: FederalKind; name?: string; agency?: string } | undefined;
    if (!props?.kind || !props.name) return;
    const content = federalCardElement({ kind: props.kind, name: props.name, agency: props.agency });
    content.addEventListener("keydown", (key) => {
      if (key.key === "Escape") close();
    });
    popup = new maplibregl.Popup({ className: "rail-popup federal-card", offset: 8, focusAfterOpen: false, closeOnClick: true })
      .setLngLat(event.lngLat)
      .setDOMContent(content)
      .addTo(map);
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") close();
  };
  map.on("click", onClick);
  window.addEventListener("keydown", onKey);
  return {
    close,
    open: () => popup !== null,
    detach() {
      close();
      map.off("click", onClick);
      window.removeEventListener("keydown", onKey);
    },
  };
}
