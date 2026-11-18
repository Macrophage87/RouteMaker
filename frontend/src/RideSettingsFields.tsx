/**
 * Ride settings' two choices, cue output and how much is said: in Settings (compact) and in a ride's More. Its own
 * module so Settings does not pull Ride mode's code into the first download (RideMode.tsx loads on first use).
 */
import { SettingRow, SettingSelect } from "./SettingRow.tsx";
import { shortLabel } from "./lib/shortLabel.ts";
import { t } from "./lib/i18n.ts";
import { VERBOSITY_LABELS, type Verbosity } from "./lib/navigate.ts";
import { OUTPUT_LABELS, type CueOutput, type RidePrefs } from "./lib/rideOutput.ts";

export function RideSettingsFields({
  prefs,
  onChange,
  idBase,
  compact = false,
}: {
  prefs: RidePrefs;
  onChange: (prefs: RidePrefs) => void;
  idBase: string;
  /** Settings: two pickers, with what each level says behind an (i); the ride's own settings keep the radios. */
  compact?: boolean;
}) {
  if (compact) {
    const levels = Object.keys(VERBOSITY_LABELS) as Verbosity[];
    return (
      <>
        <SettingRow infoId={`${idBase}-output-info`} about="say cues with">
          <SettingSelect
            label={t("Say cues with")}
            value={prefs.output}
            options={(Object.keys(OUTPUT_LABELS) as CueOutput[]).map((output) => [output, OUTPUT_LABELS[output]] as const)}
            onChange={(output) => onChange({ ...prefs, output, chosen: true })}
          />
        </SettingRow>
        <SettingRow
          infoId={`${idBase}-level-info`}
          about="how much to say"
          info={
            <ul className="setting-info-list">
              {levels.map((level) => (
                <li key={level}>{VERBOSITY_LABELS[level]}</li>
              ))}
            </ul>
          }
        >
          <SettingSelect
            label={t("How much to say")}
            value={prefs.verbosity}
            options={levels.map((level) => [level, shortLabel(VERBOSITY_LABELS[level])] as const)}
            onChange={(verbosity) => onChange({ ...prefs, verbosity, chosen: true })}
            describedBy={`${idBase}-level-info`}
          />
        </SettingRow>
      </>
    );
  }
  return (
    <>
      <fieldset className="ride-choice">
        <legend>{t("Say cues with")}</legend>
        {(Object.keys(OUTPUT_LABELS) as CueOutput[]).map((output) => (
          <label key={output} className="radio">
            <input
              type="radio"
              name={`${idBase}-output`}
              checked={prefs.output === output}
              onChange={() => onChange({ ...prefs, output, chosen: true })}
            />
            {OUTPUT_LABELS[output]}
          </label>
        ))}
      </fieldset>
      <fieldset className="ride-choice">
        <legend>{t("How much to say")}</legend>
        {(Object.keys(VERBOSITY_LABELS) as Verbosity[]).map((level) => (
          <label key={level} className="radio">
            <input
              type="radio"
              name={`${idBase}-level`}
              checked={prefs.verbosity === level}
              onChange={() => onChange({ ...prefs, verbosity: level, chosen: true })}
            />
            {VERBOSITY_LABELS[level]}
          </label>
        ))}
      </fieldset>
    </>
  );
}
