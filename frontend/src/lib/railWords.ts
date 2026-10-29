import { language, t, type Language } from "./i18n.ts";

/**
 * The ride rail's words under its buttons, shorter where the language's own word runs off a 320 px screen (the fit
 * check, 2026-10-28). Screen only: the buttons' names, which screen readers read, keep the whole phrase.
 */
const SHORT: Partial<Record<Language, Readonly<Record<string, string>>>> = {
  ar: { "Share live": "مباشر" },
  fr: { Locate: "Position", "Share live": "En direct" },
  hi: { "Share live": "लाइव" },
  ht: { Locate: "Kote m", "Share live": "An dirèk" },
  id: { Locate: "Lokasi", "Share live": "Langsung", Detour: "Memutar" },
  ps: { "Share live": "ژوندۍ" },
  pt: { "Share live": "Ao vivo" },
  ru: { "Share live": "Эфир" },
  ti: { "Share live": "ብቐጥታ" },
  tr: { Locate: "Konum", "Share live": "Canlı" },
  vi: { "Share live": "Trực tiếp", Detour: "Đi vòng" },
};

export function railWord(english: string, lang: Language = language()): string {
  return SHORT[lang]?.[english] ?? t(english, undefined, lang);
}
