import { useEffect, useState } from "react";
import { SettingRow, SettingSelect } from "./SettingRow.tsx";
import { RUN_PACE_EVENT, RUN_PACE_HELP, RUN_PACE_LABEL, paceOf, paceOptions, readRunPace, writeRunPace } from "./lib/runPace.ts";

/**
 * Run's pace (lib/runPace.ts), kept on this device: in Run's own ride settings, under Hills. Changing it plans the run
 * shown again (RUN_PACE_EVENT, App.tsx).
 */
export function RunPaceSelect({ idBase }: { idBase: string }) {
  const [mph, setMph] = useState(() => readRunPace());
  useEffect(() => {
    const changed = (event: Event) => {
      const next = paceOf((event as CustomEvent<number>).detail);
      if (next !== null) setMph(next);
    };
    window.addEventListener(RUN_PACE_EVENT, changed);
    return () => window.removeEventListener(RUN_PACE_EVENT, changed);
  }, []);
  return (
    <SettingRow infoId={`${idBase}-info`} about="running pace" info={RUN_PACE_HELP} className="run-pace">
      <SettingSelect
        label={RUN_PACE_LABEL}
        value={String(mph)}
        options={paceOptions()}
        onChange={(value) => {
          const next = paceOf(value);
          if (next === null) return;
          writeRunPace(next);
          setMph(next);
        }}
        describedBy={`${idBase}-info`}
      />
    </SettingRow>
  );
}
