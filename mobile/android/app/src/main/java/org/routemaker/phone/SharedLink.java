package org.routemaker.phone;

import java.net.URI;
import java.net.URISyntaxException;

/**
 * A RouteMaker link shared to the app from another app's Share sheet (Stephen, 2026-10-18: "can links
 * open in the app?"), or tapped: the store build takes the site's links (src/links/AndroidManifest.xml,
 * once the site's /.well-known/assetlinks.json names the app; mobile/README.md). The shared text may hold
 * words around the link ("Ride with me: https://..."); the first https link in it is taken, and only
 * when it is on the site kept on this phone. Without Android, so it is unit-tested (app/src/test).
 */
public final class SharedLink {

    private SharedLink() {}

    /**
     * What to look in for a link: a share's text, or a tapped link's address; null for any other
     * intent (the launcher, and the "Site address" shortcut, a VIEW with no address).
     */
    public static String text(String action, String sharedText, String data) {
        if ("android.intent.action.SEND".equals(action)) return sharedText == null ? "" : sharedText;
        if ("android.intent.action.VIEW".equals(action) && data != null) return data;
        return null;
    }

    /** The link to open from the shared text, or null when it holds no link to `origin`. */
    public static String find(String text, String origin) {
        if (text == null || origin == null) return null;
        for (String word : text.split("\\s+")) {
            int at = word.indexOf("https://");
            if (at < 0) continue;
            String link = trim(word.substring(at));
            return origin.equals(SiteAddress.parse(originOf(link)).origin) ? link : null;
        }
        return null;
    }

    /** "https://host[:port]" of a link, or "" when it is not one. */
    private static String originOf(String link) {
        try {
            URI uri = new URI(link);
            if (uri.getRawUserInfo() != null || uri.getHost() == null) return "";
            return "https://" + uri.getHost() + (uri.getPort() == -1 ? "" : ":" + uri.getPort());
        } catch (URISyntaxException e) {
            return "";
        }
    }

    /** Punctuation a sentence put after the link, not part of it. */
    private static String trim(String link) {
        int end = link.length();
        while (end > 0 && ".,;:!?)]}>\"'".indexOf(link.charAt(end - 1)) >= 0) end -= 1;
        return link.substring(0, end);
    }
}
