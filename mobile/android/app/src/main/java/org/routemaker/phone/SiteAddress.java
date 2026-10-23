package org.routemaker.phone;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/**
 * The site address the rider types on first launch (SetupActivity): checked here, without Android, so
 * it is unit-tested (app/src/test). The address is kept only on this phone, in the app's preferences;
 * no test build carries one (mobile/README.md).
 */
public final class SiteAddress {

    /** The fixed, public health path every RouteMaker server answers (src/config/urls.py, core.health). */
    public static final String PROBE_PATH = "/healthz";

    private SiteAddress() {}

    /** An origin ("https://host[:port]"), or the sentence to show when the text is not one. */
    public static final class Parsed {

        public final String origin;
        public final String error;

        private Parsed(String origin, String error) {
            this.origin = origin;
            this.error = error;
        }

        public boolean ok() {
            return origin != null;
        }
    }

    public static Parsed parse(String text) {
        String raw = text == null ? "" : text.trim();
        if (raw.isEmpty()) {
            return new Parsed(null, "Type the site's address, for example https://routes.example.org");
        }
        if (!raw.contains("://")) {
            raw = "https://" + raw;
        }
        URI uri;
        try {
            uri = new URI(raw);
        } catch (URISyntaxException e) {
            return new Parsed(null, "That is not a web address. Type it as https://routes.example.org");
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!scheme.equals("https")) {
            return new Parsed(null, "The address must start with https:// (a secure connection).");
        }
        String host = uri.getHost();
        if (host == null || host.isEmpty() || uri.getRawUserInfo() != null) {
            return new Parsed(null, "That is not a web address. Type it as https://routes.example.org");
        }
        String path = uri.getRawPath();
        if ((path != null && !path.isEmpty() && !path.equals("/")) || uri.getRawQuery() != null || uri.getRawFragment() != null) {
            return new Parsed(null, "Type the site's address alone, without anything after the name (no /page or ?).");
        }
        int port = uri.getPort();
        String origin = "https://" + host.toLowerCase(Locale.ROOT) + (port == -1 || port == 443 ? "" : ":" + port);
        return new Parsed(origin, null);
    }

    /** What the probe of PROBE_PATH found. */
    public enum Probe {
        /** 200 "ok": a RouteMaker server. */
        ROUTEMAKER,
        /** 503 "degraded": a RouteMaker server whose database is not answering just now. */
        ROUTEMAKER_DEGRADED,
        /** 401 asking for basic auth (the beta's password): kept; the app asks for the password next. */
        PASSWORD,
        /** Anything else: not a RouteMaker site. */
        NOT_ROUTEMAKER,
    }

    public static Probe classify(int status, String body, String wwwAuthenticate) {
        String text = body == null ? "" : body.trim();
        if (status == 200 && text.equals("ok")) return Probe.ROUTEMAKER;
        if (status == 503 && text.equals("degraded")) return Probe.ROUTEMAKER_DEGRADED;
        if (status == 401 && wwwAuthenticate != null && wwwAuthenticate.trim().toLowerCase(Locale.ROOT).startsWith("basic")) {
            return Probe.PASSWORD;
        }
        return Probe.NOT_ROUTEMAKER;
    }

    /** The sentence for a probe that does not keep the address, or null when it is kept. */
    public static String refusal(Probe probe) {
        return probe == Probe.NOT_ROUTEMAKER
            ? "That site answered, but it is not a RouteMaker site. Check the address."
            : null;
    }

    public static final String NO_ANSWER = "No answer from that address. Check it, and that the phone has a signal or Wi-Fi.";
}
