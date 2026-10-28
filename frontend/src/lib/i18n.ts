/**
 * The app's languages (the owner, 2026-10-27: "have this app compatible with multiple languages"; Spanish
 * first, the most spoken language after English in the DC area). English is the source: every phrase is
 * written in English in the code and passed through `t`, which looks it up in the language's catalog
 * (src/i18n/es.ts) and falls back to the English where a phrase has no translation yet. Street, trail
 * and place names and agency notices stay as they come; miles stay first. The route's own sentences
 * (description list, hazards, work-zone lines) come from the server already in the language: the
 * request carries `lang` (lib/api.ts routeRequestBody, the server's routemaker.lang).
 *
 * The language is read once, when the page loads: the rider's choice (Settings > Display > Language,
 * kept on this device like accessibility mode), else the device's own language. Choosing another reloads
 * the page, so the many labels the code builds once at load (module constants) follow it too.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { ES } from "../i18n/es.ts";

export type Language = "en" | "es";
/** The stored choice: "" is unset (the device's language). */
export type LanguageChoice = "" | Language;

export const LANGUAGES: readonly Language[] = ["en", "es"];
export const LANGUAGE_KEY = "routemaker.language";

/** Each language in its own words, as a language picker names them. */
export const LANGUAGE_NAME: Record<Language, string> = { en: "English", es: "Español" };

const CATALOGS: Record<Language, Readonly<Record<string, string>> | null> = { en: null, es: ES };

export function readLanguageChoice(store: KeyValueStore | null = browserStore()): LanguageChoice {
  try {
    const raw = store?.getItem(LANGUAGE_KEY);
    return raw === "en" || raw === "es" ? raw : "";
  } catch {
    return "";
  }
}

export function writeLanguageChoice(choice: LanguageChoice, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(LANGUAGE_KEY, choice);
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
}

/** The device's language, where it is one the app has: the first of the browser's that is; else English. */
export function deviceLanguage(preferred: readonly string[] | undefined = typeof navigator !== "undefined" ? navigator.languages : undefined): Language {
  for (const tag of preferred ?? []) {
    const base = tag.toLowerCase().split("-")[0];
    if (base === "en" || base === "es") return base;
  }
  return "en";
}

let current: Language = readLanguageChoice() || deviceLanguage();

/** The language in force for this page load. */
export function language(): Language {
  return current;
}

/** For tests: the language `t` translates into. The app sets it only by `chooseLanguage`'s reload. */
export function setLanguageForTest(next: Language): void {
  current = next;
}

/** The voice's language: US Spanish, so the voices made for the US are picked where a phone has several. */
export function speechLang(lang: Language = current): string {
  return lang === "es" ? "es-US" : "en-US";
}

/**
 * A phrase in the language in force, from its English. `{name}` places are filled from `vars` after the
 * lookup, so a translation can put them where its own grammar wants them.
 */
export function t(english: string, vars?: Readonly<Record<string, string | number>>, lang: Language = current): string {
  const text = CATALOGS[lang]?.[english] ?? english;
  return vars ? text.replace(/\{(\w+)\}/g, (all, key: string) => (key in vars ? String(vars[key]) : all)) : text;
}

/**
 * A short label and the rest of it, for a button that shows only its first word on a narrow screen ("Save" and
 * " route"), in the language in force: "Guardar" and " ruta".
 */
export function firstWordAndRest(text: string): [string, string] {
  const at = text.indexOf(" ");
  return at < 0 ? [text, ""] : [text.slice(0, at), text.slice(at)];
}

/** The page's own language, for screen readers and the browser's hyphenation and voice. */
export function markPageLanguage(doc: Document | undefined = typeof document !== "undefined" ? document : undefined): void {
  if (doc) doc.documentElement.lang = current;
}

/** Keeps the choice and reloads, so every label follows it. */
export function chooseLanguage(choice: LanguageChoice): void {
  writeLanguageChoice(choice);
  if ((choice || deviceLanguage()) !== current && typeof location !== "undefined") location.reload();
}
