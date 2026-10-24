package org.routemaker.phone;

import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.util.Base64;
import androidx.core.content.FileProvider;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * Send to Garmin (frontend/src/lib/sendToGarmin.ts): the site's FIT course, handed to
 * Garmin Connect when it is installed and takes the file ("Open with", the way it imports a course file from a
 * file manager, or else Share), otherwise to every app that opens it. A WebView neither
 * shares nor downloads a file the page makes, so the page hands the bytes here.
 *
 * The file is written to the app's cache (courses/, the one file sent last only) and lent to the chosen app
 * through the app's FileProvider with read access alone. Its type is the provider's answer for the file's
 * extension, as a file manager's would be. Nothing is sent anywhere by the app itself.
 * Send to Wahoo's file (frontend/src/lib/wahooLink.ts handWahooFile) passes anyApp: the "Open with" list only, never
 * Garmin Connect.
 */
@CapacitorPlugin(name = "RouteMakerFiles")
public class FilesPlugin extends Plugin {

    static final String DIR = "courses";
    /** Garmin Connect's package, the one app this plugin looks for (AndroidManifest.xml's <queries>). */
    static final String GARMIN_CONNECT = "com.garmin.android.apps.connectmobile";
    /** Well above the largest course the site makes (lib/deviceProfiles.ts, 8 MB). */
    static final int MAX_BYTES = 16_000_000;

    @PluginMethod
    public void openWith(PluginCall call) {
        String name = safeName(call.getString("name"));
        String data = call.getString("data");
        if (name == null || data == null) {
            call.reject("A file name ending .fit, .tcx or .gpx and the file's bytes are needed");
            return;
        }
        byte[] bytes;
        try {
            bytes = Base64.decode(data, Base64.NO_WRAP);
        } catch (IllegalArgumentException e) {
            call.reject("The file's bytes are not base64");
            return;
        }
        if (bytes.length == 0 || bytes.length > MAX_BYTES) {
            call.reject("The file is empty or too large");
            return;
        }
        File file;
        try {
            file = write(name, bytes);
        } catch (IOException e) {
            call.reject("Could not write the file", e);
            return;
        }
        Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", file);
        String type = getContext().getContentResolver().getType(uri);
        if (type == null) {
            type = "application/octet-stream";
        }
        // Garmin Connect itself when it takes the file, by "Open with" or by Share: one tap fewer, and the rider
        // is not left to find it in a list. Otherwise every app that opens the file, to choose from.
        // Send to Wahoo's file (anyApp): never Garmin Connect, always the list, for the rider to pick the Wahoo app.
        boolean anyApp = Boolean.TRUE.equals(call.getBoolean("anyApp", false));
        PackageManager pm = getContext().getPackageManager();
        Intent target = null;
        for (Intent candidate : anyApp ? new Intent[0] : new Intent[] { viewIntent(uri, type), sendIntent(uri, type) }) {
            candidate.setPackage(GARMIN_CONNECT);
            if (candidate.resolveActivity(pm) != null) {
                target = candidate;
                break;
            }
        }
        boolean direct = target != null;
        if (!direct) {
            target = Intent.createChooser(viewIntent(uri, type), "Open the course with");
            target.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        }
        try {
            getActivity().startActivity(target);
        } catch (ActivityNotFoundException | SecurityException e) {
            call.reject("No app on this phone opens the file", e);
            return;
        }
        JSObject result = new JSObject();
        result.put("app", direct ? "garmin-connect" : "chooser");
        call.resolve(result);
    }

    private static Intent viewIntent(Uri uri, String type) {
        Intent view = new Intent(Intent.ACTION_VIEW);
        view.setDataAndType(uri, type);
        view.setClipData(ClipData.newRawUri("", uri));
        view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        return view;
    }

    private static Intent sendIntent(Uri uri, String type) {
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType(type);
        send.putExtra(Intent.EXTRA_STREAM, uri);
        send.setClipData(ClipData.newRawUri("", uri));
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        return send;
    }

    /** The name the site gave, if it is a plain file name with a course file's extension; else null. */
    static String safeName(String name) {
        if (name == null || name.length() > 120 || !name.matches("[A-Za-z0-9._-]+") || name.startsWith(".")) {
            return null;
        }
        return name.matches(".*\\.(fit|tcx|gpx)") ? name : null;
    }

    private File write(String name, byte[] bytes) throws IOException {
        File dir = new File(getContext().getCacheDir(), DIR);
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("No cache folder");
        }
        // The file sent last only: an earlier one has been read by now, or never will be.
        File[] old = dir.listFiles();
        if (old != null) {
            for (File f : old) {
                if (!f.getName().equals(name)) {
                    //noinspection ResultOfMethodCallIgnored
                    f.delete();
                }
            }
        }
        File file = new File(dir, name);
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(bytes);
        }
        return file;
    }
}
