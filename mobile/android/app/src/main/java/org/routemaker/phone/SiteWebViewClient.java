package org.routemaker.phone;

import android.app.Activity;
import android.app.AlertDialog;
import android.view.LayoutInflater;
import android.view.View;
import android.webkit.HttpAuthHandler;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.TextView;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

/**
 * Capacitor's WebView client, plus the one thing a browser does that it does not: the HTTP basic auth
 * prompt. The beta sits behind basic auth (deploy/beta/nginx-routemaker.conf.template), and a WebView
 * without this answers its 401 with a blank page. Only for the site's own host; the name and password
 * are handed to the WebView for this run and never kept by the app (asked again on the next launch).
 */
class SiteWebViewClient extends BridgeWebViewClient {

    private final Activity activity;
    private final String siteHost;

    SiteWebViewClient(Bridge bridge, Activity activity, String siteHost) {
        super(bridge);
        this.activity = activity;
        this.siteHost = siteHost;
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
