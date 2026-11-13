import { useEffect, useRef, useState } from "react";
import { SettingRow, SettingSelect } from "./SettingRow.tsx";
import { askPersist } from "./lib/offlineRouteStore.ts";
import { sizeText } from "./lib/offlineRoutes.ts";
import {
  PACK_DOWNLOADING,
  PACK_FAILED,
  PACK_HELP,
  PACK_KEPT,
  PACK_LABEL,
  PACK_NO_LIST,
  PACK_NO_ROOM,
  PACK_NONE,
  areaName,
  downloadPack,
  fetchPackList,
  keptPack,
  removePack,
  type DownloadOutcome,
  type PackList,
} from "./lib/regionPack.ts";

const NONE = "none";

const OUTCOME_SAID: Record<DownloadOutcome, string> = { kept: PACK_KEPT, failed: PACK_FAILED, "no-room": PACK_NO_ROOM };

/**
 * Settings > Riding's map for no signal (lib/regionPack.ts): one picker, None or an area. Choosing an area downloads
 * its whole road network to this phone; None removes it. A kept area whose map has since been rebuilt is downloaded
 * again while Settings is open with a signal (the one kept stays until the new one is in).
 */
export function RegionPackSetting({ idBase }: { idBase: string }) {
  const [kept, setKept] = useState(() => keptPack());
  const [list, setList] = useState<PackList | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  // Empty at first, so a screen reader hears each change of the live line.
  const [said, setSaid] = useState("");
  const live = useRef(true);

  const download = async (id: string, found: PackList) => {
    const pack = found.packs.find((p) => p.id === id);
    if (!pack) return;
    setBusy(true);
    setSaid(PACK_DOWNLOADING);
    void askPersist();
    const outcome = await downloadPack(pack, found);
    if (!live.current) return;
    setBusy(false);
    setKept(keptPack());
    setSaid(OUTCOME_SAID[outcome]);
  };

  useEffect(() => {
    live.current = true;
    void fetchPackList().then((found) => {
      if (!live.current) return;
      setList(found);
      const now = keptPack();
      const fresh = found?.packs.find((p) => p.id === now?.id);
      // The map was rebuilt since this area was kept: the new one, in its place.
      if (found && now && fresh && fresh.sha256 !== now.sha256) void download(now.id, found);
    });
    return () => {
      live.current = false;
    };
    // Once per opening of Settings.
  }, []);

  const options: [string, string][] = [[NONE, PACK_NONE]];
  for (const pack of list?.packs ?? []) options.push([pack.id, `${areaName(pack.id, pack.name)} (${sizeText(pack.bytes)})`]);
  // Kept, but not listed (no signal): still shown, so the picker says what is on the phone.
  if (kept && !options.some(([id]) => id === kept.id)) options.push([kept.id, `${areaName(kept.id, kept.name)} (${sizeText(kept.bytes)})`]);

  const choose = (id: string) => {
    if (busy) return;
    if (id === NONE) {
      void removePack().then(() => {
        if (live.current) setKept(null);
      });
      setSaid("");
    } else if (list) void download(id, list);
    else setSaid(PACK_NO_LIST);
  };

  const status = said || (list === null && !kept ? PACK_NO_LIST : kept ? PACK_KEPT : "");
  return (
    <>
      <SettingRow infoId={`${idBase}-info`} about={PACK_LABEL} info={PACK_HELP} className="region-pack-row">
        <SettingSelect label={PACK_LABEL} value={kept?.id ?? NONE} options={options} onChange={choose} describedBy={`${idBase}-info ${idBase}-status`} />
      </SettingRow>
      <p id={`${idBase}-status`} className="hint region-pack-status" role="status">
        {status}
      </p>
    </>
  );
}
