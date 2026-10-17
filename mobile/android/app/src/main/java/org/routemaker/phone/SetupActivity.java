package org.routemaker.phone;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.pm.ShortcutInfoCompat;
import androidx.core.content.pm.ShortcutManagerCompat;
import androidx.core.graphics.drawable.IconCompat;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The launcher. With a site address kept (or a local build's own), it opens the site (MainActivity) at
 * once. Without one, it asks once: the rider types the address, it is checked against the site's
 * public /healthz (SiteAddress), and kept in the app's preferences on this phone. No build carries an
 * address, so a downloaded APK names no server.
 *
 * The launcher icon's long-press shortcut "Site address" opens this screen again to change it; clearing
 * the app's storage also brings it back.
 */
public class SetupActivity extends AppCompatActivity {

    static final String EXTRA_CHANGE = "org.routemaker.phone.CHANGE_SITE";

    private final ExecutorService probes = Executors.newSingleThreadExecutor();
    private EditText field;
    private Button go;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        boolean change = getIntent() != null && getIntent().getBooleanExtra(EXTRA_CHANGE, false);
        String address = SiteStore.address(this, SiteStore.readConfig(this));
        if (address != null && !change) {
            open();
            return;
        }
        setContentView(R.layout.activity_setup);
        field = findViewById(R.id.site_url);
        go = findViewById(R.id.site_go);
        status = findViewById(R.id.site_status);
        String saved = SiteStore.saved(this);
        if (saved != null) field.setText(saved);
        if (SiteStore.built(SiteStore.readConfig(this)) != null) {
            show(getString(R.string.setup_built_fixed));
        }
        go.setOnClickListener(v -> check());
        field.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_GO) {
                check();
                return true;
            }
            return false;
        });
    }

    @Override
    protected void onDestroy() {
        probes.shutdownNow();
        super.onDestroy();
    }

    private void check() {
        SiteAddress.Parsed parsed = SiteAddress.parse(field.getText().toString());
        if (!parsed.ok()) {
            fail(parsed.error);
            return;
        }
        go.setEnabled(false);
        show(getString(R.string.setup_checking));
        String origin = parsed.origin;
        probes.execute(() -> {
            SiteAddress.Probe probe = probe(origin);
            runOnUiThread(() -> answer(origin, probe));
        });
    }

    private void answer(String origin, SiteAddress.Probe probe) {
        if (isFinishing()) return;
        go.setEnabled(true);
        if (probe == null) {
            fail(SiteAddress.NO_ANSWER);
            return;
        }
        String refusal = SiteAddress.refusal(probe);
        if (refusal != null) {
            fail(refusal);
            return;
        }
        SiteStore.save(this, origin);
        addShortcut(this);
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        finish();
    }

    /** The probe of /healthz: null when nothing answered (no signal, no such host, a bad certificate). */
    private static SiteAddress.Probe probe(String origin) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(origin + SiteAddress.PROBE_PATH).openConnection();
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(10_000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            int status = connection.getResponseCode();
            String auth = connection.getHeaderField("WWW-Authenticate");
            InputStream in = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            return SiteAddress.classify(status, readSome(in), auth);
        } catch (IOException | RuntimeException e) {
            return null;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static String readSome(InputStream in) throws IOException {
        if (in == null) return "";
        try (InputStream stream = in) {
            byte[] buffer = new byte[64];
            int read = stream.read(buffer);
            return read <= 0 ? "" : new String(buffer, 0, read, StandardCharsets.UTF_8);
        }
    }

    private void open() {
        addShortcut(this);
        startActivity(new Intent(this, MainActivity.class));
        finish();
    }

    /**
     * Status and errors: a polite live region (activity_setup.xml), so TalkBack says each once; emptied
     * first, so the same error said again is said again.
     */
    private void show(String text) {
        status.setText("");
        status.setText(text);
        status.setVisibility(View.VISIBLE);
    }

    private void fail(String text) {
        show(text);
        field.requestFocus();
    }

    /** The launcher's long-press "Site address", to change it later. */
    static void addShortcut(Context context) {
        try {
            Intent intent = new Intent(context, SetupActivity.class);
            intent.setAction(Intent.ACTION_VIEW);
            intent.putExtra(EXTRA_CHANGE, true);
            ShortcutInfoCompat shortcut = new ShortcutInfoCompat.Builder(context, "site-address")
                .setShortLabel(context.getString(R.string.shortcut_site_short))
                .setLongLabel(context.getString(R.string.shortcut_site_long))
                .setIcon(IconCompat.createWithResource(context, R.drawable.ic_ride))
                .setIntent(intent)
                .build();
            ShortcutManagerCompat.setDynamicShortcuts(context, Collections.singletonList(shortcut));
        } catch (RuntimeException e) {
            // A launcher without shortcuts: clearing the app's storage still resets the address.
        }
    }
}
