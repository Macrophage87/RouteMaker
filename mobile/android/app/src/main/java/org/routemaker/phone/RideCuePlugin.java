package org.routemaker.phone;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.Drawable;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Riding with the phone in a pocket (backlog 2026-11-13; Stephen chose "All three, no new switches"). Three things the
 * page (frontend/src/lib/nativeShell.ts) asks for during a ride:
 *
 * - show / clear: one live turn card on the lock screen and the shade, in place of the "Latest cue" notification that
 *   kept the last sentence (and its stale distance) after the turn. The turn's arrow, the distance counting down, the
 *   street and the turn after it, updated in place, silent. On Android 16 it asks to be a Live Update (promoted ongoing),
 *   which also shows in the status bar and on the always-on display where the phone allows it.
 * - chime: a short tone just before a spoken turn cue, a different one before "off route", so the first word is not lost
 *   to wind. The page calls it inside the voice's audio turn (VoiceFocusPlugin), and speaks when it answers.
 * - buzz: a vibration at a turn's "now" cue, one pattern for left and another for right. It follows the phone's own
 *   setting: a phone set to silent gets none (no switch in the app; the owner's pick).
 *
 * Nothing is kept, logged or sent here: the card's words come from the page and are gone at clear.
 */
@CapacitorPlugin(name = "RouteMakerRideCue")
public class RideCuePlugin extends Plugin {

    /** The card's notification id; the old "Latest cue" is MainActivity.CUE_NOTICE_ID (8080). */
    static final int CARD_ID = 8081;
    static final String CHANNEL = "routemaker-turn-card";

    /**
     * Tone length, our default (unmeasured): long enough to hear in wind, short enough not to delay the turn. Off route
     * is two short beeps instead (OFF_BEEP_MS each, OFF_GAP_MS apart), so the two are told apart without words.
     */
    static final int CHIME_MS = 150;
    static final int OFF_BEEP_MS = 90;
    static final int OFF_GAP_MS = 50;
    /** The pause after the tone before the voice starts. */
    static final int CHIME_GAP_MS = 60;

    /** Buzz patterns (off, on, off, on...), our default: left one long, right two short. Unmeasured. */
    static final long[] LEFT = {0, 450};
    static final long[] RIGHT = {0, 140, 120, 140};

    /** The arrow drawables, by the page's arrow word; anything else gets the straight-on ride arrow. */
    static String arrowIcon(String arrow) {
        if (arrow == null) {
            return "ic_ride";
        }
        switch (arrow) {
            case "left":
                return "rm_arrow_left";
            case "right":
                return "rm_arrow_right";
            case "bear_left":
                return "rm_arrow_bear_left";
            case "bear_right":
                return "rm_arrow_bear_right";
            case "uturn":
                return "rm_arrow_uturn";
            case "stop":
            case "end":
                return "rm_arrow_flag";
            default:
                return "ic_ride";
        }
    }

    /** The buzz for a side, or null for none. */
    static long[] pattern(String side) {
        if ("left".equals(side)) {
            return LEFT;
        }
        if ("right".equals(side)) {
            return RIGHT;
        }
        return null;
    }

    /** A phone set to silent gets no buzz; vibrate-only and normal ringing do. */
    static boolean buzzAllowed(int ringerMode) {
        return ringerMode != AudioManager.RINGER_MODE_SILENT;
    }

    /** How many beeps a tone has: one before a turn, two before "off route". */
    static int beeps(String kind) {
        return "off".equals(kind) ? 2 : 1;
    }

    /** How long a tone and its pause take before the voice starts. */
    static int chimeMs(String kind) {
        return ("off".equals(kind) ? 2 * OFF_BEEP_MS + OFF_GAP_MS : CHIME_MS) + CHIME_GAP_MS;
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean channelMade;
    private ToneGenerator tones;

    @PluginMethod
    public void show(PluginCall call) {
        String title = call.getString("title", "");
        String body = call.getString("body", "");
        String arrow = call.getString("arrow", "");
        Context context = getContext();
        try {
            makeChannel(context);
            int icon = context.getResources().getIdentifier(arrowIcon(arrow), "drawable", context.getPackageName());
            if (icon == 0) {
                icon = R.drawable.ic_ride;
            }
            NotificationCompat.Builder card = new NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(icon)
                .setLargeIcon(bigArrow(context, icon))
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setCategory(NotificationCompat.CATEGORY_NAVIGATION)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setSound(null)
                .setVibrate(null)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setRequestPromotedOngoing(true)
                .setContentIntent(openApp(context));
            NotificationManagerCompat.from(context).notify(CARD_ID, card.build());
            call.resolve();
        } catch (SecurityException | IllegalArgumentException e) {
            // Notifications refused (Android 13+) or off: the ride goes on without the card.
            call.reject("not shown");
        }
    }

    @PluginMethod
    public void clear(PluginCall call) {
        cancel(getContext());
        call.resolve();
    }

    @PluginMethod
    public void chime(PluginCall call) {
        String kind = call.getString("kind", "turn");
        main.post(() -> {
            // The phone's own short beep (ToneGenerator.TONE_PROP_BEEP), at the music volume the voice uses.
            int length = beeps(kind) == 2 ? OFF_BEEP_MS : CHIME_MS;
            beep(length);
            if (beeps(kind) == 2) {
                main.postDelayed(() -> beep(OFF_BEEP_MS), OFF_BEEP_MS + OFF_GAP_MS);
            }
            main.postDelayed(call::resolve, chimeMs(kind));
        });
    }

    private void beep(int ms) {
        try {
            if (tones == null) {
                tones = new ToneGenerator(AudioManager.STREAM_MUSIC, 80);
            }
            tones.startTone(ToneGenerator.TONE_PROP_BEEP, ms);
        } catch (RuntimeException e) {
            // No tone generator on this phone: the voice goes on without it.
        }
    }

    @PluginMethod
    public void buzz(PluginCall call) {
        long[] waves = pattern(call.getString("side", ""));
        Context context = getContext();
        AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        Vibrator vibrator = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
        if (waves == null || audio == null || vibrator == null || !vibrator.hasVibrator() || !buzzAllowed(audio.getRingerMode())) {
            call.resolve();
            return;
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                AudioAttributes usage = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                    .build();
                vibrator.vibrate(VibrationEffect.createWaveform(waves, -1), usage);
            } else {
                vibrator.vibrate(waves, -1);
            }
        } catch (RuntimeException e) {
            // Refused by the phone: nothing to do.
        }
        call.resolve();
    }

    @Override
    protected void handleOnDestroy() {
        cancel(getContext());
        if (tones != null) {
            tones.release();
            tones = null;
        }
    }

    /** Clears the card: at End ride, and when the app starts or closes (a ride it did not end leaves no stale card). */
    static void cancel(Context context) {
        try {
            NotificationManagerCompat.from(context).cancel(CARD_ID);
        } catch (RuntimeException e) {
            // Nothing shown, or notifications off: nothing to clear.
        }
    }

    private void makeChannel(Context context) {
        if (channelMade || Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        // Default importance with no sound and no vibration: a low-importance ("silent") notification is hidden from the
        // lock screen on many phones, which is the card's whole point. Never a heads-up (that needs high importance);
        // setOnlyAlertOnce keeps TalkBack to one announcement when the card first shows, none on each update.
        NotificationChannel channel = new NotificationChannel(CHANNEL, "Turn card", NotificationManager.IMPORTANCE_DEFAULT);
        channel.setDescription("The next turn while a ride is going");
        channel.setLockscreenVisibility(android.app.Notification.VISIBILITY_PUBLIC);
        channel.enableVibration(false);
        channel.enableLights(false);
        channel.setShowBadge(false);
        channel.setSound(null, null);
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.createNotificationChannel(channel);
            channelMade = true;
        }
    }

    /** A tap on the card opens the ride. */
    private PendingIntent openApp(Context context) {
        Intent open = new Intent(context, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(context, CARD_ID, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** The arrow large: white on a dark disc, readable on light and dark shades alike. */
    private static Bitmap bigArrow(Context context, int icon) {
        int size = Math.round(64 * context.getResources().getDisplayMetrics().density);
        Bitmap bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        Paint disc = new Paint(Paint.ANTI_ALIAS_FLAG);
        disc.setColor(Color.rgb(0x20, 0x21, 0x24));
        canvas.drawCircle(size / 2f, size / 2f, size / 2f, disc);
        Drawable arrow = ContextCompat.getDrawable(context, icon);
        if (arrow != null) {
            int pad = size / 6;
            arrow = arrow.mutate();
            arrow.setTint(Color.WHITE);
            arrow.setBounds(pad, pad, size - pad, size - pad);
            arrow.draw(canvas);
        }
        return bitmap;
    }
}
