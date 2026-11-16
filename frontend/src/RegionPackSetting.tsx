import { useEffect, useRef, useState } from "react";
import { Once, later } from "./app/later.tsx";
import { SettingRow } from "./SettingRow.tsx";
import { sizeText } from "./lib/offlineRoutes.ts";
import {
  PACK_HELP,
  PACK_LABEL,
  PACK_MANAGE,
  PACK_NONE_KEPT,
  downloadPack,
  fetchPackList,
  keptPacks,
  onDownloads,
  onPhoneText,
  type KeptPack,
  type PackList,
} from "./lib/regionPack.ts";

// The popout is loaded on first use (app/later.tsx), so it stays out of the first load's size budget.
const RegionPackDialog = later(() =>
  import("./RegionPackDialog.tsx").then((m) => m.RegionPackDialog),
);

const totalBytes = (kept: KeptPack[]) =>
  kept.reduce((sum, k) => sum + k.bytes, 0);

/**
 * Settings > Riding's maps for no signal (lib/regionPack.ts): one line that says what is on this phone, and Manage, which
 * opens the popout (Stephen, 2026-11-15: "Radio buttons don't make sense here. We should instead have a popout where you
 * can download one or all, and delete one or all from your phone to save space. It should tell you what's on it"). A
 * kept area whose map has since been rebuilt is downloaded again while Settings is open with a signal (the one kept stays
 * until the new one is in).
 */
export function RegionPackSetting({ idBase }: { idBase: string }) {
  const [kept, setKept] = useState(() => keptPacks());
  const [list, setList] = useState<PackList | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    const stop = onDownloads(() => {
      if (live.current) setKept(keptPacks());
    });
    void fetchPackList().then((found) => {
      if (!live.current) return;
      setList(found);
      // The map was rebuilt since an area was kept: the new one, in its place, quietly.
      for (const k of keptPacks()) {
        const fresh = found?.packs.find((p) => p.id === k.id);
        if (found && fresh && fresh.sha256 !== k.sha256)
          void downloadPack(fresh, found);
      }
    });
    return () => {
      live.current = false;
      stop();
    };
    // Once per opening of Settings.
  }, []);

  const summary = kept.length
    ? onPhoneText(sizeText(totalBytes(kept)))
    : PACK_NONE_KEPT;
  return (
    <>
      <SettingRow
        infoId={`${idBase}-info`}
        about={PACK_LABEL}
        info={PACK_HELP}
        className="region-pack-row"
      >
        <span className="region-pack-line">
          <span className="setting-label" id={`${idBase}-label`}>
            {PACK_LABEL}
          </span>
          <span className="hint region-pack-summary" id={`${idBase}-summary`}>
            {summary}
          </span>
        </span>
        <button
          type="button"
          className="secondary"
          aria-haspopup="dialog"
          aria-describedby={`${idBase}-label ${idBase}-summary`}
          onClick={() => setOpen(true)}
        >
          {PACK_MANAGE}
        </button>
      </SettingRow>
      <Once when={open}>
        <RegionPackDialog
          open={open}
          onClose={() => setOpen(false)}
          list={list}
          kept={kept}
          onKept={() => setKept(keptPacks())}
        />
      </Once>
    </>
  );
}
