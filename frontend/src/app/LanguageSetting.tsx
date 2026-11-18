// Settings > Display > Language: the picker, and under it for a draft language the note and how to report a wrong word.
import { useState } from "react";
import { SettingRow, SettingSelect } from "../SettingRow.tsx";
import { BETA_DISCORD_TEXT, BETA_DISCORD_URL } from "../lib/betaBanner.ts";
import { LANGUAGES, LANGUAGE_NAME, chooseLanguage, language, locale, readLanguageChoice, t, type LanguageChoice } from "../lib/i18n.ts";

/** The Language setting's (i) words. Street names and notices from agencies stay as they are written. */
const LANGUAGE_HINT = "The app's words and the voice. Street names and agency notices stay as written. Changing it reloads the page.";
/**
 * Every language but English is a Claude draft (the owner, 2026-10-28): said under the picker, in the language, until
 * a native speaker has checked it. Spanish covers the whole app; the others Go and Ride, Plan staying in English.
 */
const DRAFT_NOTE = "Draft translation, not yet checked by a native speaker. Plan stays in English.";
const DRAFT_NOTE_ES = "Draft translation, not yet checked by a native speaker.";
/** How a rider reports a bad phrase (the owner, 2026-11-12): {discord} is the link to the beta Discord. */
const DRAFT_REPORT = "Spot a wrong word? Tell us on {discord}.";

/** The draft note's report line, its {discord} place the link, wherever the language's grammar put it. */
function DraftReport() {
  const [before, after = ""] = t(DRAFT_REPORT).split("{discord}");
  return (
    <p className="hint">
      {before}
      <a href={BETA_DISCORD_URL} target="_blank" rel="noopener noreferrer">
        {BETA_DISCORD_TEXT}
        <span className="visually-hidden"> {t("(opens in a new tab)")}</span>
      </a>
      {after}
    </p>
  );
}

/** Settings > Display > Language: the choice is held here too, so a pick that needs no reload still shows. */
export function LanguageSetting() {
  const [choice, setChoice] = useState<LanguageChoice>(() => readLanguageChoice());
  return (
    <>
    <SettingRow infoId="settings-language-info" about={t("Language")} info={t(LANGUAGE_HINT)}>
      <SettingSelect<LanguageChoice>
        label={t("Language")}
        value={choice}
        options={[["", t("Phone default")] as const, ...LANGUAGES.map((lang) => [lang, LANGUAGE_NAME[lang]] as const)]}
        onChange={(next) => {
          setChoice(next);
          chooseLanguage(next);
        }}
        describedBy="settings-language-info"
        optionLang={Object.fromEntries(LANGUAGES.map((lang) => [lang, locale(lang)]))}
      />
    </SettingRow>
    {language() !== "en" && <p className="hint">{language() === "es" ? t(DRAFT_NOTE_ES) : t(DRAFT_NOTE)}</p>}
    {language() !== "en" && <DraftReport />}
    </>
  );
}
