/**
 * The Surface setting (the owner, 2026-11-21: "a surface setting: paved only, gravel, easy MTB, and then MTB2-4 as
 * max"; "People here can and should be able to adjust to anything"): one picker for the roughest surface a ride may
 * use, made of the dials that plan it, on every bike of the rider's own but Road Bike (always paved).
 *
 * - Paved only: the API's `paved` (on Mountain Bike with no mountain-bike trails, `mtb_level` 0, too).
 * - Gravel: the ride type as it plans; on Mountain Bike, no mountain-bike trails (`mtb_level` 0).
 * - Easy MTB trails: `easy_mtb` (on Mountain Bike, its level 1).
 * - MTB trails up to level 2, 3 or 4: `easy_mtb` with `mtb_level` 2 to 4 (on Mountain Bike, its own levels).
 *
 * The trail choices are on the ride types that take them (`offersTrails`). What the picker shows is lib/dialsPanel.ts
 * panelView's `surface`.
 */
import { easyMtbOn, offersEasyMtb, offersPaved, type Dials } from "./dials.ts";
import { isMtb, mtbLevelOf, withMtbLevel, type MtbLevel } from "./mtbMode.ts";
import type { PresetId } from "./presets.ts";
import { t } from "./i18n.ts";

export type Surface = "paved" | "gravel" | "easy-mtb" | "mtb-2" | "mtb-3" | "mtb-4";
export const SURFACES: readonly Surface[] = ["paved", "gravel", "easy-mtb", "mtb-2", "mtb-3", "mtb-4"];

export const SURFACE_LABEL = t("Surface");
export const SURFACE_ABOUT = "surface";
export const PAVED_LABEL = t("Paved only");
export const PAVED_HINT = t("Avoids gravel and dirt wherever pavement runs near.");
export const GRAVEL_LABEL = t("Gravel");
export const GRAVEL_HINT = t("Paved and gravel roads and paths, as this ride type plans them.");
/** On Mountain Bike: its roads and paths with none of the mountain-bike trails, as after End mountain biking. */
export const MTB_GRAVEL_HINT = t("Paved and gravel roads and paths, with no mountain-bike trails.");

/** Whether the ride type has the Surface picker: a bike of the rider's own, but Road Bike. */
export function offersSurface(preset: PresetId): boolean {
  return offersPaved(preset);
}

/** Whether it takes the trail choices, Easy MTB trails up to level 4: Mountain Bike, and the ride types with Easy MTB. */
export function offersTrails(preset: PresetId): boolean {
  return isMtb(preset) || offersEasyMtb(preset);
}

/** The hardest level a trail choice keeps (Easy MTB trails is 1). */
export function levelOf(surface: Surface): number {
  return surface === "easy-mtb" ? 1 : surface.startsWith("mtb-") ? Number(surface.slice(4)) : 0;
}

/** The surface the ride plans on. */
export function surfaceOf(preset: PresetId, dials: Pick<Dials, "paved" | "easyMtb" | "trailsOff" | "mtbLevel">): Surface {
  if (isMtb(preset)) {
    if (dials.paved === true) return "paved";
    if (dials.mtbLevel === 0 || dials.trailsOff === true) return "gravel";
    return trailSurface(mtbLevelOf(dials));
  }
  if (offersPaved(preset) && dials.paved === true) return "paved";
  if (easyMtbOn(preset, dials)) {
    const level = dials.mtbLevel;
    return typeof level === "number" && level >= 2 && level <= 4 ? trailSurface(level) : "easy-mtb";
  }
  return "gravel";
}

function trailSurface(level: number): Surface {
  return level <= 1 ? "easy-mtb" : (`mtb-${level}` as Surface);
}

/**
 * The dials with a surface chosen, each part taken off the object where it is the default, so a link stays short:
 * Paved only and the trails are never both.
 */
export function withSurface(preset: PresetId, dials: Dials, surface: Surface): Dials {
  const next: Dials = { ...dials };
  delete next.paved;
  delete next.easyMtb;
  const level = levelOf(surface);
  if (surface === "paved") next.paved = true;
  if (isMtb(preset)) {
    // Mountain Bike: 0 is no trails, and no preferred level; 1 to 4 as its own levels (the default, 2, left out).
    if (level >= 1) return withMtbLevel({ ...next, mtbLevel: undefined }, level as MtbLevel);
    next.mtbLevel = 0;
    delete next.mtbPreferred;
    return next;
  }
  delete next.mtbLevel;
  if (level >= 1) next.easyMtb = true;
  if (level >= 2) next.mtbLevel = level;
  return next;
}
