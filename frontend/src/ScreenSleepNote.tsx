/**
 * The screen-on note of Ride mode and Roam (lib/rideOutput.ts ScreenWake): one line on screen, "Screen may sleep: keep
 * it on.", with the rider's own phone's steps behind its How (the UI review, 2026-10-28: the three-line note stayed for
 * the whole ride and gave an Android phone an iPhone's steps). Screen readers read the whole sentence with the steps;
 * the voice says it through the ride's own outputs.
 */
import { useId, useState } from "react";
import { WAKE_SHORT, WAKE_STEPS, wakeSaid, type PhoneKind } from "./lib/rideOutput.ts";
import { t } from "./lib/i18n.ts";
import { MenuStep } from "./MenuStep.tsx";

export function ScreenSleepNote({ note, kind }: { note: string; kind: PhoneKind }) {
  const [open, setOpen] = useState(false);
  const stepsId = useId();
  if (!note) return null;
  return (
    <div className="hint wake-note">
      <p>
        <span aria-hidden="true">{WAKE_SHORT}</span>
        <span className="visually-hidden">{wakeSaid(note, kind)}</span>{" "}
        <button
          type="button"
          className="link wake-how"
          aria-expanded={open}
          aria-controls={stepsId}
          aria-label={t("How to keep the screen on")}
          onClick={() => setOpen(!open)}
        >
          {t("How")}
        </button>
      </p>
      <p id={stepsId} className="wake-steps" hidden={!open}>
        <MenuStep text={WAKE_STEPS[kind]} />
      </p>
    </div>
  );
}
