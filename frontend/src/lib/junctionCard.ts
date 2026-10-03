/**
 * Where the keyboard focus goes around a junction's card and its markers
 * (a11y review of integrate-2, 2.4.3; OWNER-DECISIONS 220: blind stokers plan
 * routes with their pilots, so the card has to be usable by a screen reader).
 * MapView.tsx does what these say; they are kept here so they are tested
 * without a DOM.
 *
 * - A card opened from the summary's list leaves the focus on the row: the
 *   row already says everything the card does, and taking the focus into the
 *   map would leave a keyboard rider about 28 stops from the list.
 * - A card opened from a marker takes the focus (its close button), and gives
 *   it back to the marker when it closes.
 * - Escape closes the card.
 * - After a group's zoom, the focus goes to the first member's new marker.
 */
import type { JunctionGroup, JunctionItem } from "./intersectionMarkers.ts";

/** What opened the card: a marker on the map, or a row of the summary's list. */
export type CardOpener = "marker" | "list";

/** MapLibre's Popup `focusAfterOpen`: only a marker's card takes the focus. */
export function cardTakesFocus(opener: CardOpener): boolean {
  return opener === "marker";
}

/**
 * Where the focus goes when the card closes: to what opened it, if the focus
 * was in the card or was lost with it (the page's body); otherwise it stays
 * where the rider put it (a click on the map, or a Tab out to the panel).
 */
export function focusAfterClose(opener: CardOpener, focusWasInCard: boolean, focusOnBody: boolean): CardOpener | null {
  return focusWasInCard || focusOnBody ? opener : null;
}

/**
 * Whether Escape closes the card: when one is open and the focus is in it, on
 * what opened it (a marker or a list row), or on the map or nowhere. Elsewhere
 * (a dialog of the panel, the search box) Escape is that control's own.
 */
export function escapeClosesCard(cardOpen: boolean, focusAt: "card" | "opener" | "map" | "body" | "other"): boolean {
  return cardOpen && focusAt !== "other";
}

/** The card's accessible name: "Very high stress junction, at 1.2 mi (2.0 km)". */
export function cardName(item: Pick<JunctionItem, "label" | "where">): string {
  const severity = item.label.split(":")[0];
  return `${severity} junction, ${item.where.charAt(0).toLowerCase()}${item.where.slice(1)}`;
}

/** The close button's name, for MapLibre's "Close popup". */
export const CARD_CLOSE_LABEL = "Close junction card";

/** Which drawn group holds the junction at `index` (route order), or -1. */
export function groupHolding(groups: readonly Pick<JunctionGroup, "members">[], index: number): number {
  return groups.findIndex((group) => group.members.some((member) => member.index === index));
}

/**
 * The map's credits on a narrow screen (a11y review of integrate-2, 2.4.11):
 * MapLibre's compact attribution opens expanded and closes only on the first
 * drag. With the agency credits it is 904 characters and covered about 68% of
 * a 375 px phone's map, junction markers and the card's close button included.
 * At or below this width it starts as the "i" button (MapLibre's own collapsed
 * state, which a tap opens), with the OpenStreetMap credit beside it
 * (styles.css), so the credit stays on screen; wider screens keep it open.
 */
export const CREDITS_COLLAPSE_PX = 640;

/** The few parts of the attribution control's element this touches. */
export interface CreditsElement {
  classList: { contains(name: string): boolean; remove(...names: string[]): void };
}

/** Collapse the credits as MapLibre's own first drag does, if the map is narrow; whether it did. */
export function collapseCredits(element: CreditsElement | null, mapWidth: number): boolean {
  if (!element || mapWidth > CREDITS_COLLAPSE_PX) return false;
  if (!element.classList.contains("maplibregl-compact") || !element.classList.contains("maplibregl-compact-show")) return false;
  element.classList.remove("maplibregl-compact-show");
  return true;
}
