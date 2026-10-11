/**
 * The edit generation the stress tiles are asked for (OWNER-DECISIONS 441h, 460.6; core/stress_edits.py).
 *
 * An instance admin's change in the road panel updates the live table in place, and the API's tile
 * ETag carries an edit generation, so a revalidation is never answered 304 for a stale tile. But a
 * browser keeps a fresh tile for five minutes without asking, and MapLibre keeps the tiles it has
 * loaded, so the editor's own map would show the old road for a while. After a save the page asks for
 * every tile again under `?rev=<generation>` (the server ignores the parameter; it only makes the URL
 * new), and keeps asking that way, so a style rebuilt later does not go back to the old URLs.
 * It is a counter and says nothing of who edited.
 */
let rev = 0;

/** The generation the tiles are asked for; 0 until the first save of this page. */
export function tileRev(): number {
  return rev;
}

export function setTileRev(next: number): void {
  rev = Number.isSafeInteger(next) && next > 0 ? next : 0;
}

/** `?rev=3`, or nothing before the first save. */
export function revSuffix(): string {
  return rev > 0 ? `?rev=${rev}` : "";
}

/** The part of a MapLibre vector source this uses. */
export interface TileSource {
  setTiles?: (tiles: string[]) => unknown;
}

/**
 * Ask for the tiles again: the stress source and the Mass Ride source, each under the new
 * generation. Returns how many sources were told. A source that is not on the map (the Mass Ride
 * one is always there, but a test's map may not have it) is skipped.
 */
export function refreshTiles(
  map: { getSource(id: string): unknown },
  sources: ReadonlyArray<{ id: string; template: (origin: string) => string }>,
  origin: string,
  generation: number,
): number {
  setTileRev(generation);
  let told = 0;
  for (const { id, template } of sources) {
    const source = map.getSource(id) as TileSource | undefined;
    if (source && typeof source.setTiles === "function") {
      source.setTiles([template(origin)]);
      told += 1;
    }
  }
  return told;
}
