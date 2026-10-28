import { language } from "./i18n.ts";

/**
 * How Ride mode's card shows a cue (the owner, 2026-10-19: "Ride mode title takes up way too much real
 * estate"): the instruction large, what follows its first comma in small print under it, street words
 * shortened ("Florida Avenue Northeast" to "Florida Ave NE"). Shown only: the voice and screen readers keep
 * the whole sentence.
 */

// A street word is shortened only where it ends a name: after a capitalised word ("R Street", "Florida Avenue"),
// and, for a type, only before a quadrant or the end of the name ("Supreme Court" stays as it is mid-name less often
// than "Northwest Branch", which stays whole). Never in plain words such as "bike lane" or "busy road". The same
// words as the course file's (lib/course.ts STREET_WORDS).
const AFTER_NAME = String.raw`(?<=\b[A-Z0-9][\w'.-]* )`;
const QUADRANTS = ["Northwest", "Northeast", "Southwest", "Southeast", "NW", "NE", "SW", "SE"];
const NAME_END = String.raw`(?=[,.;:)]|$| (?:${QUADRANTS.join("|")})\b)`;
const TYPES: readonly [string, string][] = [
  ["Avenue", "Ave"],
  ["Street", "St"],
  ["Road", "Rd"],
  ["Boulevard", "Blvd"],
  ["Drive", "Dr"],
  ["Parkway", "Pkwy"],
  ["Place", "Pl"],
  ["Terrace", "Ter"],
  ["Lane", "Ln"],
  ["Court", "Ct"],
  ["Trail", "Trl"],
  ["Highway", "Hwy"],
  ["Circle", "Cir"],
  ["Square", "Sq"],
  ["Bridge", "Br"],
];
const SHORT: readonly [RegExp, string][] = [
  ...TYPES.map(([long, short]) => [new RegExp(`${AFTER_NAME}${long}${NAME_END}`, "g"), short] as [RegExp, string]),
  ...(
    [
      ["Northwest", "NW"],
      ["Northeast", "NE"],
      ["Southwest", "SW"],
      ["Southeast", "SE"],
    ] as const
  ).map(([long, short]) => [new RegExp(`${AFTER_NAME}${long}(?=[,.;:)]|$| [a-z])`, "g"), short] as [RegExp, string]),
];

// Spanish turn words run half again as long as the English (the owner, 2026-10-27: "use shorter words so it all
// fits"): the card shows them shorter, "Gire a la izquierda hacia" as "A la izquierda hacia". Shown only, as above.
const SHORT_ES: readonly [RegExp, string][] = [
  [/\b([Gg])ire ligeramente a la (izquierda|derecha)\b/g, "leve a la $2"],
  [/\b([Gg])ire a la (izquierda|derecha)\b/g, "a la $2"],
  [/\b([Dd])é la vuelta en U\b/g, "vuelta en U"],
  [/\b([Ii])nmediatamente\b/g, "enseguida"],
];

/** The Spanish turn words shortened, with a capital where the long words had one (the first group is that letter). */
function shortTurnsEs(text: string): string {
  return SHORT_ES.reduce(
    (out, [long, short]) =>
      out.replace(long, (_, first: string, side: unknown) => {
        const said = typeof side === "string" ? short.replace("$2", side) : short;
        return first === first.toUpperCase() ? said.charAt(0).toUpperCase() + said.slice(1) : said;
      }),
    text,
  );
}

/** "Left onto R Street Northwest." as "Left onto R St NW.". */
export function shortStreets(text: string): string {
  return SHORT.reduce((out, [long, short]) => out.replace(long, short), text);
}

/** A jog's "then immediately" shown as "then" (in Spanish "luego enseguida" as "luego"): the arrow already draws it close. */
function shortThen(text: string): string {
  return text.replace(/\b([Tt])hen immediately /g, "$1hen ").replace(/\b([Ll])uego enseguida /g, "$1uego ");
}

/** Whether a turn's words name no street: no capitalised word or number after the first ("Right", "Bear left onto the path"). */
function namesNoStreet(words: string): boolean {
  return !/\s[A-Z0-9]/.test(words);
}

/** A part that starts with "then" ("Then left onto Corregidor St NW"). */
const THEN = /^(?:Then|Luego) /i;

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The cue split at its first comma: the instruction, then the rest with a capital ("No signal mapped, busy road (LTS 3).").
 * Where the instruction names no street and a "then" after it does, that turn joins the big line (the UI review,
 * 2026-10-28: "Right, then right onto Union Station Dr NE"), so the large words always say where to go.
 */
export function cueParts(text: string): { head: string; rest: string } {
  const streets = shortThen(shortStreets(text.trim()));
  const short = language() === "es" ? shortThen(shortTurnsEs(streets)) : streets;
  const at = short.indexOf(", ");
  if (at < 0) return { head: short, rest: "" };
  let head = short.slice(0, at);
  let rest = short.slice(at + 2);
  if (namesNoStreet(head) && THEN.test(rest)) {
    const next = rest.indexOf(", ");
    const then = next < 0 ? rest : rest.slice(0, next);
    if (!namesNoStreet(then)) {
      head = `${head}, ${then.charAt(0).toLowerCase()}${then.slice(1)}`.replace(/\.$/, "");
      rest = next < 0 ? "" : rest.slice(next + 2);
    }
  }
  return { head, rest: capital(rest) };
}
