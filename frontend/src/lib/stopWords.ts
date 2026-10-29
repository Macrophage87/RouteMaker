/**
 * What each kind of stop's card says (lib/stopCard.ts), most important first: what it is, open or closed now where
 * the mapped hours can be read (else the hours cleaned up: lib/openingHours.ts), how far or the detour, then a stand's kit or a sight's
 * details. The lists say the same facts; the card adds the website and the one action.
 */
import { foodHoursText, foodHowFar, foodKindText, type FoodResult } from "./food.ts";
import type { Nearby, NearestPlace } from "./nearest.ts";
import { howFar } from "./nearest.ts";
import { categoryOf, sightHowFar, type SightPlace, type SightResult } from "./places.ts";
import { repairDetails, repairHowFar, repairTitle, type RepairNearby, type RepairPlace } from "./repair.ts";
import { openNowText, type StopCardWords } from "./stopCard.ts";

export const REPAIR_CAUTION = "From OpenStreetMap: check it is working before you count on it.";

const sentence = (text: string) => (text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}.` : "");

/** "Open now · closes 10 PM." where it can be read, else the hours cleaned up; with none mapped, `fallback` (a farm stand's seasonal note). */
function hoursLine(hours: string | undefined, at: Date, fallback: string): string {
  return openNowText(hours, at) ?? fallback;
}

export function foodWords(result: FoodResult, at: Date): StopCardWords {
  const { place } = result;
  const hours = foodHoursText(place, at);
  return { title: place.name, lines: [`${foodKindText(place)}.`, ...(hours ? [hours] : []), foodHowFar(result)], website: place.website };
}

export function sightWords(place: SightPlace, at: Date, result?: SightResult): StopCardWords {
  const hours = hoursLine(place.hours, at, "");
  const how = result ? sightHowFar(result) : "";
  // "+0.4 mi (0.6 km)" alone is a detour off the route (lib/places.ts sightHowFar).
  const far = how.startsWith("+") ? `${how} detour.` : sentence(how);
  return { title: place.name, lines: [`${categoryOf(place).one}.`, ...(hours ? [hours] : []), ...(far ? [far] : [])], website: place.website };
}

export function repairWords(place: RepairPlace, at: Date, item?: RepairNearby): StopCardWords {
  const far = item ? sentence(repairHowFar(item)) : "";
  // The caution the repair card always had (a stand may be broken, a shop's hours out of date).
  return { title: repairTitle(place), lines: [...repairDetails(place, at), ...(far ? [far] : []), REPAIR_CAUTION], website: place.website };
}

/** Water, a restroom or a Metro station from the nearest list. */
export function nearbyWords(item: Nearby): StopCardWords {
  return placeWords(item.place, sentence(howFar(item)));
}

export function placeWords(place: NearestPlace, far = ""): StopCardWords {
  return { title: place.title, lines: [...place.details, ...(far ? [far] : [])] };
}
