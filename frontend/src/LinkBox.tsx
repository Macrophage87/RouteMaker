/**
 * The link, in a box to select and copy, where neither the share sheet nor the clipboard took it (Stephen 2026-11-22:
 * "It's not intuitive to copy a link when no share sheet"). Under the line that says so (COPY_LINK_FAILED): Copy link's,
 * Share's, and Save's. The whole link is selected as the box takes the focus, so a long press or Ctrl+C copies it.
 */
import { t } from "./lib/i18n.ts";

export function LinkBox({ link }: { link: string }) {
  if (!link) return null;
  return (
    <input
      type="text"
      className="link-box"
      readOnly
      value={link}
      aria-label={t("Link")}
      autoFocus
      onFocus={(event) => event.currentTarget.select()}
      onClick={(event) => event.currentTarget.select()}
    />
  );
}
