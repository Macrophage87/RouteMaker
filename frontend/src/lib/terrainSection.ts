/**
 * The Layers sheet's Trails and terrain section (lib/layerSection.ts): which of its layers the section switch
 * counts, and what its row says while it is closed. A layer that cannot show (topo lines with no archive on the
 * server; mountain-bike trails without the stress map, whose tiles carry them) is left out of the switch, so
 * the row never reads On or Some on with nothing drawn; its own switch, inside, says why.
 */
import { climbsStatusText, CLIMBS_LABEL } from "./climbsLegend.ts";
import type { ClimbsStatus } from "./climbs.ts";
import type { SectionLayer } from "./layerSection.ts";
import { MTB_TRAILS_LABEL } from "./mtbTrailsSwitch.ts";
import { TOPO_LINES_LABEL } from "./topoLines.ts";

export interface TerrainState {
  mtb: boolean;
  climbs: boolean;
  topo: boolean;
  /** The stress tiles are on the page (App's `stress === "available"`). */
  stressAvailable: boolean;
  /** False once a check found no topo archive on the server. */
  topoReady: boolean;
  climbsStatus: ClimbsStatus;
}

/** The row's words, while it is closed, for a layer the rider has on that cannot show. */
export const MTB_TRAILS_ROW_UNAVAILABLE = "Mountain-bike trails need the stress map, unavailable for now.";
export const TOPO_LINES_ROW_UNAVAILABLE = "Topo lines are not available on this server yet.";

/** The layers the section switch turns on and off: the ones that can show. */
export function terrainLayers(state: TerrainState): SectionLayer[] {
  return [
    ...(state.stressAvailable ? [{ key: "mtb", label: MTB_TRAILS_LABEL, on: state.mtb }] : []),
    { key: "climbs", label: CLIMBS_LABEL, on: state.climbs },
    ...(state.topoReady ? [{ key: "topo", label: TOPO_LINES_LABEL, on: state.topo }] : []),
  ];
}

/**
 * The section's status line: empty while it is open (each layer's own line says it there); closed, the
 * climbs' loading or unavailable words, and a layer the rider has on that cannot show.
 */
export function terrainStatus(open: boolean, state: TerrainState): string {
  if (open) return "";
  return [
    climbsStatusText(state.climbs, state.climbsStatus),
    state.mtb && !state.stressAvailable ? MTB_TRAILS_ROW_UNAVAILABLE : "",
    state.topo && !state.topoReady ? TOPO_LINES_ROW_UNAVAILABLE : "",
  ]
    .filter(Boolean)
    .join(" ");
}
