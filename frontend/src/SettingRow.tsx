import { useState, type ReactNode } from "react";
import { Icon } from "./Icon.tsx";
import { t } from "./lib/i18n.ts";

/**
 * One setting on one line (Settings tidy, Stephen 2026-10-17: "picker inputs and the like and put info
 * within a (i) icon"): the setting's name and its control, then an (i) button that shows or hides the
 * explanation under the line. The explanation stays in the page while hidden, so a control that points
 * `aria-describedby` at `infoId` still has it read as its description.
 */
export function SettingRow({ infoId, about, info, children, className }: { infoId: string; about: string; info?: ReactNode; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={className ? `setting-row ${className}` : "setting-row"}>
      <div className="setting-line">
        {children}
        {info ? <InfoButton open={open} onToggle={() => setOpen((was) => !was)} controls={infoId} about={about} /> : <span className="info-spacer" aria-hidden="true" />}
      </div>
      {info && (
        <div id={infoId} className="hint setting-info" hidden={!open}>
          {info}
        </div>
      )}
    </div>
  );
}

/** The (i) button on its own, where the explanation it opens is laid out by its caller. */
export function InfoButton({ open, onToggle, controls, about }: { open: boolean; onToggle: () => void; controls: string; about: string }) {
  return (
    <button type="button" className="info-tip" aria-expanded={open} aria-controls={controls} onClick={onToggle}>
      <Icon name="info" size={18} />
      <span className="visually-hidden">{t("About {about}", { about })}</span>
    </button>
  );
}

/** A labelled picker: the name, then a native select of `options` (value, words). */
export function SettingSelect<T extends string>({
  label,
  value,
  options,
  onChange,
  describedBy,
  className,
  optionLang,
}: {
  label: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (next: T) => void;
  describedBy?: string;
  className?: string;
  /** An option's own language, where it is not the page's ("Español" on an English page), for a screen reader. */
  optionLang?: Partial<Record<T, string>>;
}) {
  return (
    <label className={className ? `select-setting ${className}` : "select-setting"}>
      <span className="setting-name">{label}</span>
      <select value={value} aria-describedby={describedBy} onChange={(event) => onChange(event.target.value as T)}>
        {options.map(([option, words]) => (
          <option key={option} value={option} lang={optionLang?.[option]}>
            {words}
          </option>
        ))}
      </select>
    </label>
  );
}
