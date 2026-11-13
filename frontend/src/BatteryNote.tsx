/**
 * The battery-saver line at the first Start ride in the Android app (lib/batteryNote.ts): one line and a button to
 * RouteMaker's App info page, where "Battery, Unrestricted" is. Shown until the rider closes it or presses the button.
 */
import { useEffect, useState } from "react";
import { t } from "./lib/i18n.ts";
import { BATTERY_FIX, BATTERY_LINE, batteryNoteDue, markBatteryNoteSeen, openBatterySettings } from "./lib/batteryNote.ts";

/** `onDone`: where the focus goes once the line is gone (the ride's heading), so it is not dropped to the page. */
export function BatteryNote({ onDone }: { onDone?: () => void }) {
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
          markBatteryNoteSeen();
          setShown(false);
          onDone?.();
        }}
      >
        {BATTERY_FIX()}
      </button>{" "}
      <button
        type="button"
        className="link"
        onClick={() => {
          markBatteryNoteSeen();
          setShown(false);
          onDone?.();
        }}
      >
        {t("Close")}
      </button>
    </p>
  );
}
