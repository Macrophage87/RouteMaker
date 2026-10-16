package org.routemaker.phone;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Bitmap;
import android.net.Uri;
import android.view.LayoutInflater;
import android.view.View;
import android.webkit.HttpAuthHandler;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.TextView;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;
import java.util.Locale;

/**
 * Capacitor's WebView client, plus two things:
 *
 * - Which page is on top: `topLevelIsSite()` is true only while the top-level page is the kept site
 *   (GuardedBridge passes bridge calls to Capacitor only then). Set false before a top-level navigation
 *   leaves the site (shouldOverrideUrlLoading, server redirects included), and set again as each
 *   top-level page starts (onPageStarted: back and forward too).
 * - The HTTP basic auth prompt a browser has and a WebView does not. The beta sits behind basic auth
 *   (deploy/beta/nginx-routemaker.conf.template), and a WebView without this answers its 401 with a
 *   blank page. Only for the site's own host; the name and password are handed to the WebView for this
 *   run and never kept by the app (asked again on the next launch).
 */
class SiteWebViewClient extends BridgeWebViewClient {

    private final Activity activity;
    private final String siteOrigin;
    private final String siteHost;
    private volatile boolean onSite = false;

    SiteWebViewClient(Bridge bridge, Activity activity, String siteOrigin) {
        super(bridge);
        this.activity = activity;
        this.siteOrigin = origin(Uri.parse(siteOrigin));
        this.siteHost = Uri.parse(siteOrigin).getHost();
    }

    /** "scheme://host[:port]", lower case; the default port left out, as SiteAddress keeps it. */
    static String origin(Uri uri) {
        if (uri == null || uri.getScheme() == null || uri.getHost() == null) return null;
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        int port = uri.getPort();
        boolean plain = port == -1 || (scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80);
        return scheme + "://" + uri.getHost().toLowerCase(Locale.ROOT) + (plain ? "" : ":" + port);
    }

    private boolean isSite(Uri uri) {
        String o = origin(uri);
        return o != null && o.equals(siteOrigin);
    }

    boolean topLevelIsSite() {
        return onSite;
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        if (request.isForMainFrame() && !isSite(request.getUrl())) {
            onSite = false;
        }
        return super.shouldOverrideUrlLoading(view, request);
    }

    @Override
    public void onPageStarted(WebView view, String url, Bitmap favicon) {
        onSite = url != null && isSite(Uri.parse(url));
        super.onPageStarted(view, url, favicon);
    }

    @Override
    public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler, String host, String realm) {
        if (activity.isFinishing() || siteHost == null || !siteHost.equalsIgnoreCase(host)) {
            handler.cancel();
            return;
        }
        View form = LayoutInflater.from(activity).inflate(R.layout.dialog_site_login, null);
        EditText user = form.findViewById(R.id.login_user);
        EditText password = form.findViewById(R.id.login_password);
        TextView about = form.findViewById(R.id.login_about);
        about.setText(activity.getString(R.string.login_about, host));
        new AlertDialog.Builder(activity)
            .setTitle(R.string.login_title)
            .setView(form)
            .setCancelable(false)
            .setPositiveButton(R.string.login_go, (dialog, which) -> handler.proceed(user.getText().toString(), password.getText().toString()))
            .setNegativeButton(R.string.login_cancel, (dialog, which) -> handler.cancel())
            .show();
    }
}
