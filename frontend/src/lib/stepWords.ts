/**
 * The stress steps' words, in a module of their own so the route's colours (routeColours.ts) can name a half
 * step without the suggestion form's imports.
 */
/** Every step's words (core/segment_info.py STEP_WORDS; OWNER-DECISIONS 441i, 441l). */
export const STEP_WORDS: Readonly<Record<string, string>> = {
  "1": "Comfortable for everyone",
  "1.5": "Probably comfortable for older children",
  "2": "Fine for adults",
  "2.5": "Fine for most confident adults",
  "3": "For experienced cyclists",
  "3.5": "Stressful even for experienced cyclists",
  "4": "High stress: busy, fast traffic",
  "4.5": "A very high-stress road",
  "5": "Avoid",
};
