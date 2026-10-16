package org.routemaker.phone;

import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import com.getcapacitor.Bridge;
import com.getcapacitor.Logger;
import com.getcapacitor.MessageHandler;
import java.lang.reflect.Field;

/**
 * The native bridge, for the kept site only.
 *
 * The background-geolocation plugin needs Capacitor's legacy bridge (`android.useLegacyBridge`, its
 * README: otherwise fixes stop after five minutes in the background). The legacy bridge is a
 * `WebView.addJavascriptInterface` object, which Android hands to every page and frame the WebView
 * shows, whatever its origin: Discord's sign-in pages too. So this object takes its place: the same
 * name ("androidBridge") and the same `postMessage`, but a message is passed to Capacitor only while
 * the WebView's top-level page is the kept site (SiteWebViewClient tracks it); otherwise it is dropped.
 *
 * Capacitor's handler is its private `Bridge.msgHandler` (Capacitor 8.5.3, pinned; mobile/test checks
 * the field is still there). If it cannot be found, the bridge is removed and not replaced: the app
 * then has no native location or voice, rather than a bridge open to every origin.
 */
final class GuardedBridge {

    static final String NAME = "androidBridge";

    private final MessageHandler handler;
    private final SiteWebViewClient client;

    private GuardedBridge(MessageHandler handler, SiteWebViewClient client) {
        this.handler = handler;
        this.client = client;
    }

    /** Called on the UI thread right after the bridge is made, before the first page commits. */
    static void install(Bridge bridge, SiteWebViewClient client) {
        if (!bridge.getConfig().isUsingLegacyBridge()) {
            // The web-message bridge: Capacitor already limits it to the main frame.
            return;
        }
        WebView webView = bridge.getWebView();
        MessageHandler handler = null;
        try {
            Field field = Bridge.class.getDeclaredField("msgHandler");
            field.setAccessible(true);
            handler = (MessageHandler) field.get(bridge);
        } catch (ReflectiveOperationException | RuntimeException e) {
            Logger.error("RouteMaker", "Capacitor's message handler was not found: the native bridge is off", e);
        }
        webView.removeJavascriptInterface(NAME);
        if (handler != null) {
            webView.addJavascriptInterface(new GuardedBridge(handler, client), NAME);
        }
    }

    /** From the page's native-bridge.js, on the WebView's JavaBridge thread. */
    @JavascriptInterface
    @SuppressWarnings("unused")
    public void postMessage(String json) {
        if (!client.topLevelIsSite()) {
            Logger.warn("RouteMaker", "A bridge call from a page other than the site was ignored");
            return;
        }
        handler.postMessage(json);
    }
}
