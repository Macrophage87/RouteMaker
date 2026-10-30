import { useLayoutEffect, useRef } from "react";
import type { SeeEveryone } from "./app/useSeeEveryone.ts";
import { Icon } from "./Icon.tsx";
import { t } from "./lib/i18n.ts";
import { railWord } from "./lib/railWords.ts";

/**
 * See everyone on the ride's and Roam's side buttons (lib/seeEveryone.ts): there while any other rider's dot is on the
 * map; pressed while the view that frames them all is on. Its word under it as the rail's others, or none with icons only.
 */
export function SeeEveryoneButton({ everyone }: { everyone: SeeEveryone | null | undefined }) {
  if (!everyone?.shown) return null;
  return <EveryoneButton everyone={everyone} />;
}

function EveryoneButton({ everyone }: { everyone: SeeEveryone }) {
  const button = useRef<HTMLButtonElement>(null);
  const focused = useRef(false);
  // Gone with the focus on it (every dot back in view): the focus goes to the rail's first button, Where am I?.
  useLayoutEffect(() => {
    const rail = button.current?.closest(".ride-rail") ?? null;
    return () => {
      if (focused.current) rail?.querySelector<HTMLElement>(".ride-round")?.focus();
    };
  }, []);
  return (
    <button
      type="button"
      ref={button}
      className={`ride-round${everyone.on ? " ride-round-on" : ""}`}
      onClick={everyone.toggle}
      onFocus={() => (focused.current = true)}
      onBlur={() => (focused.current = false)}
      aria-pressed={everyone.on}
      aria-label={t("See everyone on the ride")}
      title={t("See everyone on the ride")}
    >
      <Icon name="users" size={24} />
      <span className="ride-word" aria-hidden="true">{railWord("Everyone")}</span>
    </button>
  );
}
