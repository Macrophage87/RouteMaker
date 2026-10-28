/**
 * Under a notice that the iPhone Home Screen app's location is blocked: where in iPhone Settings to turn it on, folded
 * so the notice stays one line. Nothing for any other notice. lib/geolocation.ts has the words.
 */
import { MenuStep } from "./MenuStep.tsx";
import { IOS_LOCATION_HELP_TITLE, IOS_LOCATION_LAST_RESORT, IOS_LOCATION_STEPS, showsIosLocationHelp } from "./lib/geolocation.ts";

export function IosLocationHelp({ notice }: { notice: string | null | undefined }) {
  if (!showsIosLocationHelp(notice)) return null;
  return (
    <details className="fold ios-location-help">
      <summary>{IOS_LOCATION_HELP_TITLE}</summary>
      <ol className="fold-body">
        {IOS_LOCATION_STEPS.map((step) => (
          <li key={step}>
            <MenuStep text={step} />
          </li>
        ))}
      </ol>
      <p className="fold-body">{IOS_LOCATION_LAST_RESORT}</p>
    </details>
  );
}
