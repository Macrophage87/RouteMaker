package org.routemaker.phone;

import android.content.Intent;
import android.os.Bundle;
import androidx.core.app.NotificationManagerCompat;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.CapConfig;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The site, in Capacitor's WebView. Opened by SetupActivity once a site address is kept on this phone;
 * the address goes into the bridge's config here, since no build carries one (mobile/README.md).
 */
public class MainActivity extends BridgeActivity {

    /** The site's "Latest cue" notification (frontend/src/lib/nativeShell.ts CUE_NOTICE_ID). */
    static final int CUE_NOTICE_ID = 8080;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // A cue left on the shade by a ride the app did not end (killed, or swiped away): never stale.
        cancelCueNotice();
        // Before super.onCreate: the bridge loads its plugins, then the site.
        registerPlugin(RideCompatPlugin.class);
        registerPlugin(FilesPlugin.class);
        JSONObject json = SiteStore.readConfig(this);
        String address = SiteStore.address(this, json);
        if (json == null) {
            // No capacitor.config.json (a build without `cap sync`): no site can be opened properly.
            address = null;
        }
        if (address != null) {
            try {
                JSONObject server = json.optJSONObject("server");
                if (server == null) {
                    server = new JSONObject();
                    json.put("server", server);
                }
                server.put("url", address);
                config = new CapConfig(getAssets(), json);
            } catch (JSONException e) {
                address = null;
            }
        }
        super.onCreate(savedInstanceState);
        if (address == null || bridge == null) {
            // No address (the app's storage was cleared while it ran): ask for it again.
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }
        SiteWebViewClient client = new SiteWebViewClient(bridge, this, address);
        bridge.setWebViewClient(client);
        // Same UI turn as the bridge's first load, so before any page commits: bridge calls from the site only.
        GuardedBridge.install(bridge, client);
        openShared(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        openShared(intent);
    }

    /** A link shared to the app (SetupActivity, SharedLink): already checked to be on the kept site. */
    private void openShared(Intent intent) {
        String link = intent == null ? null : intent.getStringExtra(SetupActivity.EXTRA_LINK);
        if (link != null && bridge != null) bridge.getWebView().loadUrl(link);
    }

    @Override
    public void onDestroy() {
        // The page that kept the cue notification up is going: so is the notification.
        cancelCueNotice();
        super.onDestroy();
    }

    private void cancelCueNotice() {
        try {
            NotificationManagerCompat.from(this).cancel(CUE_NOTICE_ID);
        } catch (RuntimeException e) {
            // Nothing shown, or notifications off: nothing to clear.
        }
    }
}
