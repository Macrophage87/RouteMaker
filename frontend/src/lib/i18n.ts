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

/**
 * The languages (the owner, 2026-10-28: "These are all the languages supported in DC", the city's Language ID
 * poster): English and Spanish in the whole app; the rest in Go and Ride (the owner: "planning requires nuances
 * that can't be easily done by automatic translation"), Plan staying in English. Mandarin ("zh") is written in
 * Simplified characters, Cantonese ("yue") in Traditional. Every catalog but English is a Claude draft.
 */
export const LANGUAGES = [
  "en", "es", "am", "ar", "bn", "yue", "fa", "fr", "ht", "hi", "id", "ja", "ko", "zh", "ps", "pt", "ru", "th", "ti", "tr", "vi",
] as const;
export type Language = (typeof LANGUAGES)[number];
/** The stored choice: "" is unset (the device's language). */
export type LanguageChoice = "" | Language;

export const LANGUAGE_KEY = "routemaker.language";

/** Each language in its own words, as a language picker names them. */
export const LANGUAGE_NAME: Record<Language, string> = {
  en: "English",
  es: "Español",
  am: "አማርኛ",
  ar: "العربية",
  bn: "বাংলা",
  yue: "廣東話",
  fa: "فارسی",
  fr: "Français",
  ht: "Kreyòl ayisyen",
  hi: "हिन्दी",
  id: "Bahasa Indonesia",
  ja: "日本語",
  ko: "한국어",
  zh: "中文（普通话）",
  ps: "پښتو",
  pt: "Português",
  ru: "Русский",
  th: "ไทย",
  ti: "ትግርኛ",
  tr: "Türkçe",
  vi: "Tiếng Việt",
};

/** The languages written right to left: the page is mirrored for them (markPageLanguage). */
export const RIGHT_TO_LEFT: ReadonlySet<Language> = new Set<Language>(["ar", "fa", "ps"]);

/**
 * Each language's tag for the page, dates and numbers: the script named for Chinese, so the browser picks a
 * Simplified or a Traditional font.
 */
const LOCALE: Record<Language, string> = {
  en: "en-US", es: "es-US", am: "am-ET", ar: "ar", bn: "bn", yue: "yue-Hant-HK", fa: "fa-IR", fr: "fr", ht: "ht",
  hi: "hi-IN", id: "id-ID", ja: "ja-JP", ko: "ko-KR", zh: "zh-Hans-CN", ps: "ps-AF", pt: "pt-BR", ru: "ru-RU",
  th: "th-TH", ti: "ti-ER", tr: "tr-TR", vi: "vi-VN",
};

/**
 * The voice's language, and the other tags a phone may file its voice under (Cantonese is "yue-HK" on some, "zh-HK"
 * on others). US Spanish, so the voices made for the US are picked where a phone has several.
 */
const VOICE: Record<Language, readonly string[]> = {
  en: ["en-US"], es: ["es-US", "es-MX", "es"], am: ["am-ET", "am"], ar: ["ar-SA", "ar"], bn: ["bn-BD", "bn-IN", "bn"],
  yue: ["yue-HK", "zh-HK", "yue"], fa: ["fa-IR", "fa"], fr: ["fr-FR", "fr"], ht: ["ht-HT", "ht"], hi: ["hi-IN", "hi"],
  id: ["id-ID", "in-ID", "id"], ja: ["ja-JP", "ja"], ko: ["ko-KR", "ko"], zh: ["zh-CN", "cmn-CN", "zh"], ps: ["ps-AF", "ps"],
  pt: ["pt-BR", "pt"], ru: ["ru-RU", "ru"], th: ["th-TH", "th"], ti: ["ti-ER", "ti-ET", "ti"], tr: ["tr-TR", "tr"], vi: ["vi-VN", "vi"],
};

/**
 * The catalogs (src/i18n/<language>.ts). Spanish is in the bundle; the others are fetched before the app starts
 * (loadLanguage, main.tsx), so a rider downloads only the one they read. The service worker keeps them all.
 */
const LOADERS: Partial<Record<Language, () => Promise<Readonly<Record<string, string>>>>> = {
  am: () => import("../i18n/am.ts").then((m) => m.CATALOG),
  ar: () => import("../i18n/ar.ts").then((m) => m.CATALOG),
  bn: () => import("../i18n/bn.ts").then((m) => m.CATALOG),
  yue: () => import("../i18n/yue.ts").then((m) => m.CATALOG),
  fa: () => import("../i18n/fa.ts").then((m) => m.CATALOG),
  fr: () => import("../i18n/fr.ts").then((m) => m.CATALOG),
  ht: () => import("../i18n/ht.ts").then((m) => m.CATALOG),
  hi: () => import("../i18n/hi.ts").then((m) => m.CATALOG),
  id: () => import("../i18n/id.ts").then((m) => m.CATALOG),
  ja: () => import("../i18n/ja.ts").then((m) => m.CATALOG),
  ko: () => import("../i18n/ko.ts").then((m) => m.CATALOG),
  zh: () => import("../i18n/zh.ts").then((m) => m.CATALOG),
  ps: () => import("../i18n/ps.ts").then((m) => m.CATALOG),
  pt: () => import("../i18n/pt.ts").then((m) => m.CATALOG),
  ru: () => import("../i18n/ru.ts").then((m) => m.CATALOG),
  th: () => import("../i18n/th.ts").then((m) => m.CATALOG),
  ti: () => import("../i18n/ti.ts").then((m) => m.CATALOG),
  tr: () => import("../i18n/tr.ts").then((m) => m.CATALOG),
  vi: () => import("../i18n/vi.ts").then((m) => m.CATALOG),
};
const CATALOGS: Partial<Record<Language, Readonly<Record<string, string>>>> = { es: ES };

function isLanguage(raw: unknown): raw is Language {
  return typeof raw === "string" && (LANGUAGES as readonly string[]).includes(raw);
}

export function readLanguageChoice(store: KeyValueStore | null = browserStore()): LanguageChoice {
  try {
    const raw = store?.getItem(LANGUAGE_KEY);
    return isLanguage(raw) ? raw : "";
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

/** A device's language tag as one of the app's: Cantonese by its Hong Kong or Macau Chinese, Dari as Farsi. */
function fromTag(tag: string): Language | null {
  const parts = tag.toLowerCase().split(/[-_]/);
  const base = parts[0];
  if (base === "zh") return parts.includes("hk") || parts.includes("mo") ? "yue" : "zh";
  if (base === "cmn") return "zh";
  if (base === "prs" || base === "pes") return "fa";
  if (base === "in") return "id";
  return isLanguage(base) ? base : null;
}

/** The device's language, where it is one the app has: the first of the browser's that is; else English. */
export function deviceLanguage(preferred: readonly string[] | undefined = typeof navigator !== "undefined" ? navigator.languages : undefined): Language {
  for (const tag of preferred ?? []) {
    const lang = fromTag(tag);
    if (lang) return lang;
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
  return VOICE[lang][0];
}

/** Every tag a phone may file this language's voice under, the first the one asked for. */
export function voiceTags(lang: Language = current): readonly string[] {
  return VOICE[lang];
}

/** The language's tag for dates and numbers ("es-US", "zh-Hans-CN"). */
export function locale(lang: Language = current): string {
  return LOCALE[lang];
}

/** Whether the language in force is written right to left. */
export function rightToLeft(lang: Language = current): boolean {
  return RIGHT_TO_LEFT.has(lang);
}

/** The catalog of the language in force, fetched once before the app starts; English if it cannot be had. */
export async function loadLanguage(lang: Language = current): Promise<void> {
  const load = LOADERS[lang];
  if (!load || CATALOGS[lang]) return;
  try {
    CATALOGS[lang] = await load();
  } catch {
    // Offline before the worker kept it: English this visit, as for any phrase not yet translated.
  }
}

/** For tests: a catalog as if loadLanguage had fetched it. */
export function setCatalogForTest(lang: Language, catalog: Readonly<Record<string, string>>): void {
  CATALOGS[lang] = catalog;
}

/** A language's catalog, or null for English or one not loaded: to read a phrase back to its English. */
export function catalogOf(lang: Language = current): Readonly<Record<string, string>> | null {
  return CATALOGS[lang] ?? null;
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
  if (!doc) return;
  doc.documentElement.lang = LOCALE[current];
  doc.documentElement.dir = rightToLeft() ? "rtl" : "ltr";
}

/** Keeps the choice and reloads, so every label follows it. */
export function chooseLanguage(choice: LanguageChoice): void {
  writeLanguageChoice(choice);
  if ((choice || deviceLanguage()) !== current && typeof location !== "undefined") location.reload();
}

/** A language's phrases read back: the exact ones by their words, the ones with {places} as patterns. */
interface Reverse {
  exact: Map<string, string>;
  patterns: { re: RegExp; english: string; names: string[] }[];
}
const REVERSE = new Map<Language, Reverse>();

function reverseOf(lang: Language): Reverse | null {
  const catalog = CATALOGS[lang];
  if (!catalog) return null;
  let found = REVERSE.get(lang);
  if (!found) {
    found = { exact: new Map(), patterns: [] };
    for (const [english, text] of Object.entries(catalog)) {
      const names = [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
      if (!names.length) {
        if (!found.exact.has(text)) found.exact.set(text, english);
        continue;
      }
      const body = text.split(/\{\w+\}/).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("(.+?)");
      found.patterns.push({ re: new RegExp(`^${body}$`, "s"), english, names });
    }
    // The longest pattern first: the one with the most fixed words is the likeliest phrase.
    found.patterns.sort((a, b) => b.re.source.length - a.re.source.length);
    REVERSE.set(lang, found);
  }
  return found;
}

/** The sentence ends a phrase may carry, in the scripts of the app's languages. */
const SENTENCE_END = /(?<=[.!?。！？।።؟])\s*/u;

function phraseToEnglish(text: string, rev: Reverse, depth: number): string | null {
  const exact = rev.exact.get(text);
  if (exact !== undefined) return exact;
  for (const { re, english, names } of rev.patterns) {
    const m = re.exec(text);
    if (!m) continue;
    const vars: Record<string, string> = {};
    // A place's own words may be a phrase too ("the path", an ordinal); a name stays as it is.
    names.forEach((name, i) => (vars[name] = (depth < 2 && phraseToEnglish(m[i + 1], rev, depth + 1)) || m[i + 1]));
    return english.replace(/\{(\w+)\}/g, (all, key: string) => vars[key] ?? all);
  }
  return null;
}

/**
 * Words said in the language in force, read back to their English (the voice where a phone has no voice for the
 * language): whole, else sentence by sentence; null where a sentence is not one of the catalog's phrases.
 */
export function englishOf(text: string, lang: Language = current): string | null {
  if (lang === "en") return text;
  const rev = reverseOf(lang);
  if (!rev) return text;
  const whole = phraseToEnglish(text.trim(), rev, 0);
  if (whole !== null) return whole;
  const sentences = text.trim().split(SENTENCE_END).filter(Boolean);
  if (sentences.length < 2) return null;
  const english = sentences.map((s) => phraseToEnglish(s, rev, 0));
  return english.every((s) => s !== null) ? english.join(" ") : null;
}
