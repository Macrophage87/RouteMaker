// The share card's few names the first load needs (Plan's button label, the shared link's Home zone), apart from
// lib/shareCard.ts so the card's arithmetic and words load with its dialog on first use (the v0.27.0 size budget).
import { METRES_PER_MILE } from "./format.ts";
import { t } from "./i18n.ts";

/** The button beside Share in Plan's More, and the dialog's heading. */
export const SHARE_IMAGE_LABEL = t("Share as image");

/** No part of the line, and no pin, is drawn within this of Home: 0.2 mi. */
export const HOME_TRIM_M = 0.2 * METRES_PER_MILE;
/** The hidden circle's centre is moved this far from Home (and its radius grown by as much), so its edge does not point at Home. */
export const ZONE_SHIFT_MIN_M = 60;
export const ZONE_SHIFT_MAX_M = 150;
/** The hidden circle's radius, the same however far its centre moved, so the gap's size says nothing of the shift. */
export const ZONE_RADIUS_M = HOME_TRIM_M + ZONE_SHIFT_MAX_M + 1;
