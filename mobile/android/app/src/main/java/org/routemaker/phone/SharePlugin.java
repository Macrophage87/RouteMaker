package org.routemaker.phone;

import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Parcelable;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The share sheet for the site's Share route, Share ride and Broadcast (frontend/src/lib/nativeShell.ts
 * nativeShareNavigator). Android's WebView has no navigator.share, so in the app those buttons were hidden
 * (Stephen, 2026-10-26: "I don't seem to be able to broadcast rides"). The page hands the title, text and link
 * here, and Android's chooser sends them as plain text to the app the rider picks. Nothing is sent anywhere by
 * the app itself, and nothing is kept.
 *
 * The chooser does not say whether the rider sent the link or backed out: the call resolves once it opens.
 */
@CapacitorPlugin(name = "RouteMakerShare")
public class SharePlugin extends Plugin {

    /** Well above the longest link the site makes (a plan of 25 points and its shared line's id). */
    static final int MAX_CHARS = 8_000;

    @PluginMethod
    public void share(PluginCall call) {
        String url = call.getString("url");
        String text = call.getString("text", "");
        String title = call.getString("title", "");
        if (!linkOk(url) || text.length() > MAX_CHARS || title.length() > MAX_CHARS) {
            call.reject("A web link to share is needed");
            return;
        }
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType("text/plain");
        send.putExtra(Intent.EXTRA_TEXT, body(text, url));
        if (!title.isEmpty()) {
            send.putExtra(Intent.EXTRA_SUBJECT, title);
        }
        Intent chooser = Intent.createChooser(send, title.isEmpty() ? null : title);
        // Not to RouteMaker itself (it takes shared links, SetupActivity): the rider is sending the link on.
        chooser.putExtra(Intent.EXTRA_EXCLUDE_COMPONENTS, new Parcelable[] { new ComponentName(getContext(), SetupActivity.class) });
        try {
            getActivity().startActivity(chooser);
        } catch (ActivityNotFoundException | SecurityException e) {
            call.reject("No app on this phone shares a link", e);
            return;
        }
        call.resolve();
    }

    /** A web link of a sensible length: the site only shares its own pages. */
    static boolean linkOk(String url) {
        return url != null && url.length() <= MAX_CHARS && (url.startsWith("https://") || url.startsWith("http://"));
    }

    /** The text, then the link on its own line, as a browser's share sheet hands both to a chat app. */
    static String body(String text, String url) {
        return text.isEmpty() ? url : text + "\n" + url;
    }
}
