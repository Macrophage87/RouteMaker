/**
 * Colors and Units: in Settings > Display, and in a ride's settings popup (Stephen 2026-11-03: "People should also be
 * able to switch to metric or dark modes from these settings"). One copy, so the two never differ.
 */
import { useState, useSyncExternalStore } from "react";
import { InfoButton, SettingRow, SettingSelect } from "./SettingRow.tsx";
import { AccessibilitySwitch } from "./lib/accessibilitySwitch.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, subscribePalette } from "./stressStyle.js";
import { t } from "./lib/i18n.ts";
import { THEME_CHOICES, chooseTheme, readThemeChoice, type ThemeChoice } from "./lib/themeClock.ts";
import { chooseUnits, switchUnitsInRide, units, type Units } from "./lib/units.ts";

/**
 * Settings > Display > Units (the owner, 2026-11-03: "have a metric mode in settings"): US (miles first, metric in
 * brackets) or Metric (kilometres first, US in brackets; Ride says metres and kilometres). Reloads, as Language does.
 */
export function UnitsSetting({ idBase, saveNow, inRide = false }: { idBase: string; saveNow?: () => Promise<boolean>; inRide?: boolean }) {
  const [choice, setChoice] = useState<Units>(() => units());
  const [unsaved, setUnsaved] = useState(false);
  return (
    <>
    <SettingRow infoId={`${idBase}-units-info`} about={t("Units")} info={
        // In a ride it switches at once (switchUnitsInRide), so no word of a reload there.
        inRide
          ? t("Distances, speeds and heights, on screen and spoken. The other units stay in brackets.")
          : t("Distances, speeds and heights, on screen and spoken. The other units stay in brackets. Changing it reloads the page.")
      }>
      <SettingSelect<Units>
        label={t("Units")}
        value={choice}
        options={[["us", t("Miles and feet")] as const, ["metric", t("Kilometers and meters")] as const]}
        onChange={(next) => {
          setChoice(next);
          setUnsaved(false);
          // Signed in, the account is saved first; not saved, the choice goes back and says so.
          // In a ride, no reload: it switches at once and the ride carries on (switchUnitsInRide).
          if (inRide) {
            void switchUnitsInRide(next, saveNow).then((switched) => {
              if (!switched && units() !== next) {
                setChoice(units());
                setUnsaved(true);
              }
            });
            return;
          }
          void chooseUnits(next, saveNow).then((reloaded) => {
            if (!reloaded && units() !== next) {
              setChoice(units());
              setUnsaved(true);
            }
          });
        }}
        describedBy={`${idBase}-units-info`}
      />
    </SettingRow>
    {unsaved && <p className="notice" role="status">{t("Units were not saved to your account; try again shortly.")}</p>}
    </>
  );
}

/**
 * Settings > Display > Colors (the owner, 2026-11-01: "There's the ability to use whatever setting you want still?"):
 * the sun by default, or the phone's own setting, or always light or dark (lib/themeClock.ts). It shows at once.
 */
export function ThemeSetting({ idBase }: { idBase: string }) {
  const [choice, setChoice] = useState<ThemeChoice>(() => readThemeChoice());
  const words: Record<ThemeChoice, string> = {
    sun: t("Sunrise and sunset"),
    phone: t("Phone's setting"),
    light: t("Always light"),
    dark: t("Always dark"),
  };
  return (
    <SettingRow infoId={`${idBase}-theme-info`} about={t("Colors")} info={t("Sunrise and sunset: light by day, dark from sunset to sunrise, which also saves battery on most phones.")}>
      <SettingSelect<ThemeChoice>
        label={t("Colors")}
        value={choice}
        options={THEME_CHOICES.map((id) => [id, words[id]] as const)}
        onChange={(next) => {
          setChoice(next);
          chooseTheme(next);
        }}
        describedBy={`${idBase}-theme-info`}
      />
    </SettingRow>
  );
}

/**
 * High contrast in the ride's settings popup, as Settings has it (app/Sheets.tsx ContrastRow), with its explanation
 * behind an (i); shown as it is now, wherever it was changed.
 */
export function ContrastRow({ idBase }: { idBase: string }) {
  const [open, setOpen] = useState(false);
  const on = useSyncExternalStore(subscribePalette, accessibilityOn);
  return (
    <div className="setting-row contrast-row">
      <AccessibilitySwitch
        idBase={idBase}
        on={on}
        source={accessibilitySource()}
        paletteFromAddress={paletteSetByAddress()}
        onChange={(on) => setAccessibility(on)}
        hintHidden={!open}
      />
      <InfoButton open={open} onToggle={() => setOpen((was) => !was)} controls={`${idBase}-hint`} about="high contrast" />
    </div>
  );
}
