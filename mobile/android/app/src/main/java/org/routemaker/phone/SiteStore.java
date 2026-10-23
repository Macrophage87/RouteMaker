package org.routemaker.phone;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Where the site address lives: the app's own preferences on this phone (cleared with the app's
 * storage, which brings the first-launch screen back). A local build or the store build may instead
 * carry one from ROUTEMAKER_URL in capacitor.config.json (never a CI test build); that one wins, since
 * it was asked for.
 */
final class SiteStore {

    private static final String PREFS = "routemaker";
    private static final String KEY = "site_url";

    private SiteStore() {}

    static String saved(Context context) {
        String url = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null);
        return url == null || url.isEmpty() ? null : url;
    }

    static void save(Context context, String origin) {
        SharedPreferences.Editor editor = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit();
        editor.putString(KEY, origin);
        editor.apply();
    }

    /** The address a local build was made with (capacitor.config.json server.url), or null. */
    static String built(JSONObject config) {
        JSONObject server = config == null ? null : config.optJSONObject("server");
        String url = server == null ? null : server.optString("url", null);
        return url == null || url.isEmpty() ? null : url;
    }

    /** The app's capacitor.config.json (written by `cap sync`), or null if unreadable. */
    static JSONObject readConfig(Context context) {
        try (InputStream in = context.getAssets().open("capacitor.config.json")) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            return new JSONObject(out.toString(StandardCharsets.UTF_8.name()));
        } catch (IOException | JSONException e) {
            return null;
        }
    }

    static String address(Context context, JSONObject config) {
        String built = built(config);
        return built != null ? built : saved(context);
    }
}
