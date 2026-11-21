/**
 * The Surface setting (the owner, 2026-11-21: "a surface setting: paved only, gravel, easy MTB, and then MTB2-4 as
 * max"): one picker for the roughest surface a ride may use, made of the dials that already plan it. Paved only is
 * the API's `paved`, Gravel is the ride type as it plans, and Easy MTB trails is `easyMtb` (Default and Trailmaxxing).
 * Mountain Bike's own Hardest trail level is its surface (levels 1 to 4), so this picker is not on it; nor on Road Bike,
 * which is always paved, or a ride type with no bike of the rider's own. What the picker shows is lib/dialsPanel.ts
 * panelView's `surface`.
 */
import { easyMtbOn, offersPaved, type Dials } from "./dials.ts";
import type { PresetId } from "./presets.ts";
import { t } from "./i18n.ts";

export type Surface = "paved" | "gravel" | "easy-mtb";

export const SURFACE_LABEL = t("Surface");
export const SURFACE_ABOUT = "surface";
export const PAVED_LABEL = t("Paved only");
export const PAVED_HINT = t("Avoids gravel and dirt wherever pavement runs near.");
export const GRAVEL_LABEL = t("Gravel");
export const GRAVEL_HINT = t("Paved and gravel roads and paths, as this ride type plans them.");

/** The surface the ride plans on: Paved only, Easy MTB trails where it is in use, else Gravel. */
export function surfaceOf(preset: PresetId, dials: Pick<Dials, "paved" | "easyMtb" | "trailsOff">): Surface {
  if (offersPaved(preset) && dials.paved === true) return "paved";
  if (easyMtbOn(preset, dials)) return "easy-mtb";
  return "gravel";
}

/** The dials with a surface chosen: Paved only and Easy MTB trails never both, and each taken off the object when off. */
export function withSurface(dials: Dials, surface: Surface): Dials {
  const next: Dials = { ...dials };
  delete next.paved;
  delete next.easyMtb;
  if (surface === "paved") next.paved = true;
  if (surface === "easy-mtb") next.easyMtb = true;
  return next;
}
