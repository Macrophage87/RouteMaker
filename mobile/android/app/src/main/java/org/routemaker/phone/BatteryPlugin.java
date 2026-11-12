package org.routemaker.phone;

import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.Locale;

/**
 * Whether the phone's battery saver may stop a ride (backlog 2026-11-12, "Ready for a dozen testers"; the owner,
 * 2026-11-12: one line at the first Start ride). Some makers' battery savers stop foreground services, so the cues go
 * silent mid-ride with no explanation (mobile/README.md, battery). The page (frontend/src/lib/batteryNote.ts) asks
 * check() at the first Start ride and, where it says so, shows one line with a button that calls openSettings().
 *
 * openSettings opens RouteMaker's own App info page, where Android 12 and later (and Samsung's One UI) keep "Battery,
 * Unrestricted". It never asks for REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, which Play restricts. Nothing is kept here.
 */
@CapacitorPlugin(name = "RouteMakerBattery")
public class BatteryPlugin extends Plugin {

    /**
     * Makers whose battery savers are known to stop foreground services (dontkillmyapp.com's list, our default).
     * Compared with Build.MANUFACTURER in lower case.
     */
    static final String[] STRICT_MAKERS = {
        "samsung", "xiaomi", "redmi", "poco", "huawei", "honor", "oneplus", "oppo", "realme", "vivo", "meizu",
        "asus", "tecno", "infinix", "nokia", "lenovo", "motorola", "sony", "wiko", "blackview", "ulefone"
    };

    static boolean strictMaker(String manufacturer) {
        String maker = manufacturer == null ? "" : manufacturer.toLowerCase(Locale.ROOT).trim();
        for (String strict : STRICT_MAKERS) {
            if (maker.equals(strict)) {
                return true;
            }
        }
        return false;
    }

    @PluginMethod
    public void check(PluginCall call) {
        Context context = getContext();
        PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        boolean optimised = power != null && !power.isIgnoringBatteryOptimizations(context.getPackageName());
        JSObject answer = new JSObject();
        answer.put("optimised", optimised);
        answer.put("strictMaker", strictMaker(Build.MANUFACTURER));
        call.resolve(answer);
    }

    @PluginMethod
    public void openSettings(PluginCall call) {
        Context context = getContext();
        Intent details = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context.getPackageName()));
        details.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(details);
        } catch (ActivityNotFoundException missing) {
            Intent list = new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
            list.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                context.startActivity(list);
            } catch (ActivityNotFoundException alsoMissing) {
                call.reject("no settings page");
                return;
            }
        }
        call.resolve();
    }
}
