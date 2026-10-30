import type { SeeEveryone } from "./app/useSeeEveryone.ts";
import { Icon } from "./Icon.tsx";
import { t } from "./lib/i18n.ts";
import { railWord } from "./lib/railWords.ts";

/**
 * See everyone on the ride's and Roam's side buttons (lib/seeEveryone.ts): only while a rider's dot is out of view, or
 * the view that frames them all is on (shown pressed). Its word under it as the rail's others, or none with icons only.
 */
export function SeeEveryoneButton({ everyone }: { everyone: SeeEveryone | null | undefined }) {
  if (!everyone?.shown) return null;
  return (
    <button
      type="button"
      className={`ride-round${everyone.on ? " ride-round-on" : ""}`}
      onClick={everyone.toggle}
      aria-pressed={everyone.on}
      aria-label={t("See everyone on the ride")}
      title={t("See everyone on the ride")}
    >
      <Icon name="users" size={24} />
      <span className="ride-word" aria-hidden="true">{railWord("Everyone")}</span>
    </button>
  );
}
