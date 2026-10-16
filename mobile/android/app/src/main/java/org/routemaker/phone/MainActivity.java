package org.routemaker.phone;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.CapConfig;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The site, in Capacitor's WebView. Opened by SetupActivity once a site address is kept on this phone;
 * the address goes into the bridge's config here, since no build carries one (mobile/README.md).
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Before super.onCreate: the bridge loads its plugins, then the site.
        registerPlugin(RideCompatPlugin.class);
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
        bridge.setWebViewClient(new SiteWebViewClient(bridge, this, Uri.parse(address).getHost()));
    }
}
