import { useState } from "react";
import { SettingRow } from "./SettingRow.tsx";
import { AVOID_STAIRS_HELP, AVOID_STAIRS_LABEL, readAvoidStairs, writeAvoidStairs } from "./lib/avoidStairs.ts";
import { t } from "./lib/i18n.ts";

/**
 * Avoid stairs on walks (lib/avoidStairs.ts), one setting kept on this device: in Settings, and in Walk and
 * Walk + 🚆🚌's own ride settings (Stephen, 2026-11-02: "Walk need not avoid stairs unless selected, but make that a
 * clear option"). Turning it plans the route shown again (lib/avoidStairs.ts AVOID_STAIRS_EVENT, App.tsx).
 */
export function AvoidStairsSwitch({ idBase }: { idBase: string }) {
  const [on, setOn] = useState(() => readAvoidStairs());
  return (
    <SettingRow infoId={`${idBase}-info`} about="avoid stairs" info={AVOID_STAIRS_HELP} className="avoid-stairs-row">
      <button
        type="button"
        role="switch"
        className="switch"
        aria-checked={on}
        aria-labelledby={`${idBase}-label`}
        aria-describedby={`${idBase}-info`}
        onClick={() => {
          writeAvoidStairs(!on);
          setOn(!on);
        }}
      >
        <span id={`${idBase}-label`} className="switch-label">
          {AVOID_STAIRS_LABEL}
        </span>
        <span className="switch-state" aria-hidden="true">
          {on ? t("On") : t("Off")}
        </span>
      </button>
    </SettingRow>
  );
}
