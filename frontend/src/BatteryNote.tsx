/**
 * The battery-saver line at the first Start ride in the Android app (lib/batteryNote.ts): one line and a button to
 * RouteMaker's App info page, where "Battery, Unrestricted" is. Shown once; Close or the button takes it away.
 */
import { useEffect, useState } from "react";
import { t } from "./lib/i18n.ts";
import { BATTERY_FIX, BATTERY_LINE, batteryNoteDue, openBatterySettings } from "./lib/batteryNote.ts";

export function BatteryNote() {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    let live = true;
    void batteryNoteDue().then((due) => live && setShown(due));
    return () => {
      live = false;
    };
  }, []);
  if (!shown) return null;
  return (
    <p className="hint battery-note">
      {BATTERY_LINE()}{" "}
      <button
        type="button"
        className="link"
        onClick={() => {
          void openBatterySettings();
          setShown(false);
        }}
      >
        {BATTERY_FIX()}
      </button>{" "}
      <button type="button" className="link" onClick={() => setShown(false)}>
        {t("Close")}
      </button>
    </p>
  );
}
