package org.routemaker.phone;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Before super.onCreate: the bridge loads its plugins, then the site.
        registerPlugin(RideCompatPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
