/**
 * A map card kept in the part of the map the panel does not cover (Stephen 2026-10-19: "when pressing the metro in
 * go mode the popup makes it hard to use"). MapLibre places a card inside the whole map, and on a phone the Go sheet
 * covers the map's lower half, so a station's card could open under it. The map is panned just enough instead.
 */

/** A box in pixels from the map's top left corner. */
export interface Box {
  top: number;
  left: number;
  bottom: number;
  right: number;
}

/**
 * How far to pan the map ([x, y], in pixels, as for map.panBy) so `card` sits inside `room`. Where the card is
 * taller or wider than the room, its top (left) edge is kept in view: the name and the buttons come first.
 */
export function popupPan(card: Box, room: Box): [number, number] {
  const along = (start: number, end: number, roomStart: number, roomEnd: number): number => {
    if (start < roomStart || end - start > roomEnd - roomStart) return start - roomStart;
    if (end > roomEnd) return end - roomEnd;
    return 0;
  };
  return [along(card.left, card.right, room.left, room.right), along(card.top, card.bottom, room.top, room.bottom)];
}

interface PannableMap {
  getContainer(): HTMLElement;
  panBy(offset: [number, number], options?: { duration?: number }): unknown;
}

/** Pan `map` so the open card `element` is clear of the panel; `padding` is the map's framing (App's framePadding). */
export function fitPopup(map: PannableMap, element: HTMLElement, padding: { top: number; left: number; bottom: number; right: number }, instant: boolean) {
  const frame = map.getContainer().getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const card = { top: rect.top - frame.top, left: rect.left - frame.left, bottom: rect.bottom - frame.top, right: rect.right - frame.left };
  // Below the top buttons (Menu, Go/Plan, Layers); a smaller margin than a route's framing above the panel, so a card
  // may cover the attribution.
  const room = { top: padding.top + 24, left: Math.max(padding.left - 32, 8), right: frame.width - 8, bottom: frame.height - Math.max(padding.bottom - 60, 8) };
  const [x, y] = popupPan(card, room);
  if (Math.abs(x) >= 1 || Math.abs(y) >= 1) map.panBy([x, y], { duration: instant ? 0 : 250 });
}
