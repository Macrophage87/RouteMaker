package org.routemaker.phone;

import android.net.Uri;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.getcapacitor.Logger;
import com.getcapacitor.Plugin;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;

/**
 * Injects assets/routemaker-compat.js at document start, for the site's origin only, so a site deployed
 * before v0.8.0 gets background location and the native voice through the browser APIs it already
 * calls (see the script's header and mobile/README.md). From v0.8.0 the site marks itself and the
 * script stands aside.
 *
 * A plugin, not MainActivity code, because the bridge loads its plugins before it loads the page: the
 * script is in place for the very first navigation. It has no methods.
 */
@CapacitorPlugin(name = "RouteMakerCompat")
public class RideCompatPlugin extends Plugin {

    static final String SCRIPT = "routemaker-compat.js";

    @Override
    public void load() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            Logger.warn("RouteMakerCompat", "This WebView cannot run a document-start script; an older site keeps browser location.");
            return;
        }
        String server = getBridge().getServerUrl();
        if (server == null) {
            return;
        }
        Uri uri = Uri.parse(server);
        String origin = uri.getScheme() + "://" + uri.getAuthority();
        try {
            WebViewCompat.addDocumentStartJavaScript(getBridge().getWebView(), readScript(), Collections.singleton(origin));
        } catch (IOException | IllegalArgumentException ex) {
            Logger.error("RouteMakerCompat", "Could not add the compatibility script", ex);
        }
    }

    private String readScript() throws IOException {
        try (InputStream in = getContext().getAssets().open(SCRIPT)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }
}
