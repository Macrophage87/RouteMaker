/**
 * Home, Work and Favorites in Go's Where to? (Stephen 2026-11-01, "Can voice recognition recognize home and work in the
 * search?"): words that name a saved place list it first, above the places searched, typed or said. "Home" or "Work"
 * (in English or the language in force, with the everyday words for them: "casa", "maison", "домой"), or a favorite's
 * own name said whole, is exact: said into the microphone (lib/placeDictation.ts) it routes there at once, as the chip
 * would. Part of a saved name ("Joe" for "Joe's Bikes") lists it. The places are the rider's own and are never kept as
 * recent places (PlaceSearch.tsx).
 */
import type { Home } from "./myGo.ts";
import { homeName } from "./homeSet.ts";
import type { FavoritePlace } from "./favoritePlaces.ts";
import type { Place } from "./geocode.ts";
import { language, t, type Language } from "./i18n.ts";

/** A saved place listed in the search: Home, Work, or another favorite. */
export const SAVED_KINDS: ReadonlySet<string> = new Set(["home", "work", "favorite"]);

/** The everyday words for Home and Work in each language, beside the app's own ("Home", "Work" and their catalogs'). */
const WORDS: Record<Language, { home: readonly string[]; work: readonly string[] }> = {
  en: { home: ["home", "house", "my house"], work: ["work", "office", "the office", "my office", "job"] },
  es: { home: ["casa", "mi casa", "hogar"], work: ["trabajo", "mi trabajo", "oficina", "la oficina"] },
  am: { home: ["ቤት", "ቤቴ"], work: ["ሥራ", "ስራ", "ቢሮ"] },
  ar: { home: ["المنزل", "البيت", "منزلي", "بيتي"], work: ["العمل", "عملي", "المكتب"] },
  bn: { home: ["বাড়ি", "বাসা"], work: ["কাজ", "অফিস"] },
  yue: { home: ["屋企", "返屋企", "家"], work: ["公司", "返工", "辦公室"] },
  fa: { home: ["خانه", "منزل", "خونه"], work: ["محل کار", "سر کار", "کار", "اداره"] },
  fr: { home: ["domicile", "maison", "la maison", "chez moi"], work: ["travail", "boulot", "bureau", "le bureau"] },
  ht: { home: ["lakay", "kay", "lakay mwen"], work: ["travay", "biwo"] },
  hi: { home: ["घर"], work: ["काम", "ऑफिस", "दफ्तर"] },
  id: { home: ["rumah"], work: ["kantor", "tempat kerja"] },
  ja: { home: ["自宅", "家", "いえ", "うち"], work: ["職場", "会社", "仕事"] },
  ko: { home: ["집", "우리 집"], work: ["직장", "회사"] },
  zh: { home: ["家", "回家"], work: ["公司", "单位", "上班"] },
  ps: { home: ["کور"], work: ["کار", "دفتر"] },
  pt: { home: ["casa", "minha casa"], work: ["trabalho", "escritório"] },
  ru: { home: ["дом", "домой"], work: ["работа", "на работу", "работу", "офис"] },
  th: { home: ["บ้าน", "กลับบ้าน"], work: ["ที่ทำงาน", "ออฟฟิศ"] },
  ti: { home: ["ገዛ", "ገዛይ"], work: ["ስራሕ", "ቤት ጽሕፈት"] },
  tr: { home: ["ev", "eve", "evim"], work: ["iş", "işe", "ofis"] },
  vi: { home: ["nhà", "về nhà"], work: ["nơi làm việc", "chỗ làm", "công ty"] },
};

/** Words said before a place: "take me home", "go to work", "llévame a casa". */
const LEADS = ["navigate to", "take me to", "take me", "go to", "go", "to", "llevame a", "llevame", "ir a", "vamos a"];

/** Lower case, accents and punctuation gone, one space between words (as lib/placeDictation.ts reads a row's name). */
function plain(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function withoutLead(said: string): string {
  for (const lead of LEADS) if (said.startsWith(`${lead} `)) return said.slice(lead.length + 1);
  return said;
}

/** What the words name: Home, Work, or nothing of the two. */
function namesKind(said: string, lang: Language): "home" | "work" | null {
  const words = (kind: "home" | "work") => [t(kind === "home" ? "Home" : "Work", undefined, lang), ...WORDS.en[kind], ...WORDS[lang][kind]].map(plain);
  for (const s of [said, withoutLead(said)]) {
    if (words("home").includes(s)) return "home";
    if (words("work").includes(s)) return "work";
  }
  return null;
}

export interface SavedHits {
  /** The saved places the words name, the exact one first. */
  places: Place[];
  /** The one the words name exactly ("home", "work", a favorite's name said whole), or null. */
  exact: Place | null;
}

/** The saved places the box's words name (none for fewer than 2 letters). */
export function savedPlacesFor(
  query: string,
  home: Home | null,
  favorites: readonly FavoritePlace[] | null,
  lang: Language = language(),
): SavedHits {
  const said = plain(query);
  if ([...said].length < 2) return { places: [], exact: null };
  const kind = namesKind(said, lang);
  const work = favorites?.find((place) => place.work) ?? null;
  const asHome = home ? { name: t("Home"), label: homeName(home), lon: home.point[0], lat: home.point[1], kind: "home" } : null;
  const asWork = work ? { name: t("Work"), label: work.label, lon: work.point[0], lat: work.point[1], kind: "work" } : null;
  const others = (favorites ?? []).filter((place) => !place.work);
  const asFavorite = (place: FavoritePlace): Place => ({ name: place.label, label: place.label, lon: place.point[0], lat: place.point[1], kind: "favorite" });
  const exact: Place | null =
    kind === "home" ? asHome : kind === "work" ? asWork : (() => {
      const named = others.find((place) => plain(place.label) === said || plain(place.label) === withoutLead(said));
      return named ? asFavorite(named) : null;
    })();
  // Part of a saved name: Home's and Work's (their addresses or names) and each favorite's, from its first letters.
  const starts = (label: string) => plain(label).startsWith(said);
  const listed: Place[] = [
    ...(asHome && kind !== "home" && starts(asHome.label) ? [asHome] : []),
    ...(asWork && kind !== "work" && starts(asWork.label) ? [asWork] : []),
    ...others.filter((place) => starts(place.label)).map(asFavorite),
  ].filter((place) => !exact || place.lon !== exact.lon || place.lat !== exact.lat);
  return { places: exact ? [exact, ...listed] : listed, exact };
}
