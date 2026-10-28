/** One step of a phone's settings, with its menu names in bold (lib/menuNames.ts). */
import { menuParts } from "./lib/menuNames.ts";

export function MenuStep({ text }: { text: string }) {
  return (
    <>
      {menuParts(text).map((part, i) => (part.menu ? <strong key={i}>{part.text}</strong> : part.text))}
    </>
  );
}
