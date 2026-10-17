/**
 * Where "the middle of the map" is for the rider (the owner, 2026-10-17: "the current location centered"): the
 * part of the map not under Go's bar or the panel. On a phone the panel is a sheet along the bottom; wider, a
 * card down the left. The answer is an offset for MapLibre's `flyTo` (pixels from the map container's own
 * centre), so a centred point lands in the open part of the map without leaving MapLibre's padding set.
 */
export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export function visibleCentreOffset(map: Box, topBarBottom: number, panel: Box | null, narrow: boolean): [number, number] {
  const top = Math.max(map.top, Math.min(topBarBottom, map.bottom));
  let left = map.left;
  let bottom = map.bottom;
  if (panel !== null && narrow) bottom = Math.max(top, Math.min(panel.top, map.bottom));
  else if (panel !== null) left = Math.max(map.left, Math.min(panel.right, map.right));
  const x = (left + map.right) / 2 - (map.left + map.right) / 2;
  const y = (top + bottom) / 2 - (map.top + map.bottom) / 2;
  return [Math.round(x), Math.round(y)];
}
