import { Icon } from "./Icon.tsx";
import { alertLine, nwsLinkName, NWS_LINK, RAIN_CREDIT, RAIN_CREDIT_NAME, RAIN_CREDIT_URL, rainLine, WEATHER_DISMISS_NAME, type WeatherReport } from "./lib/weather.ts";

/**
 * Weather along the route (lib/weather.ts), one line each: the NWS alerts first, each with its link to the NWS's
 * page, then the rain coming. Nothing when there is nothing to say. Before Start in the route's warnings; in a ride
 * in the bottom panel, with Dismiss as a big button at its side (Stephen 2026-10-24: "Make dismiss a big button on the
 * side. People will see this riding"). `part` splits it for Go (the owner's P1, 2026-10-28): the alerts under the
 * totals, the rain with the warnings; "all" is both, once each.
 */
export function WeatherLines({
  report,
  riding,
  now,
  onDismiss,
  part = "all",
}: {
  report: WeatherReport | null;
  riding: boolean;
  now: number;
  onDismiss?: () => void;
  part?: "all" | "alerts" | "rain";
}) {
  const alerts = part === "rain" ? [] : (report?.alerts ?? []);
  const rain = part === "alerts" ? null : (report?.rain ?? null);
  if (!report || (alerts.length === 0 && !rain)) return null;
  return (
    <div className={onDismiss ? "weather-lines weather-riding" : `weather-lines weather-${part}`}>
      <ul className="note-lines" role="list">
        {alerts.map((alert) => (
          <li key={alert.id} className={`note-line notice weather-alert weather-${alert.severity.toLowerCase()}`}>
            <Icon name="warn" size={16} />
            <span className="note-text">
              {alertLine(alert, now)}{" "}
              <a href={alert.url} target="_blank" rel="noopener noreferrer" aria-label={nwsLinkName(alert)}>
                {NWS_LINK}
              </a>
            </span>
          </li>
        ))}
        {rain && (
          <li className="note-line hint weather-rain">
            <Icon name="rain" size={16} />
            <span className="note-text">
              {rainLine(rain, report.alongM, riding)}{" "}
              <a className="weather-credit" href={RAIN_CREDIT_URL} target="_blank" rel="noopener noreferrer" aria-label={RAIN_CREDIT_NAME}>
                {RAIN_CREDIT}
              </a>
            </span>
          </li>
        )}
      </ul>
      {onDismiss && (
        <button type="button" className="secondary weather-dismiss" onClick={onDismiss} aria-label={WEATHER_DISMISS_NAME}>
          <Icon name="x" size={26} />
          Dismiss
        </button>
      )}
    </div>
  );
}
