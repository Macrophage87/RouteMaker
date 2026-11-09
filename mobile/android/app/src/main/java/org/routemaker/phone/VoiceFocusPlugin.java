package org.routemaker.phone;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Ride cues over music (Stephen 2026-11-08: "the voice cues are sometimes quieter than other volumes on the phone").
 * The text-to-speech plugin speaks without asking Android for audio focus, so a podcast or music app playing at the
 * same time kept its full volume and the cue was heard under it. A navigation app asks for a short turn first: music
 * dips for the sentence (and a spoken podcast pauses), then comes back. The page (frontend/src/lib/nativeShell.ts)
 * calls duck before each cue and unduck when it ends or is cut off.
 *
 * The turn is let go a moment after unduck, so a "Then left" straight after a turn does not make the music bounce, and
 * never held longer than MAX_HOLD_MS, so a page that stops answering (killed mid-sentence) cannot leave music quiet.
 * Nothing is spoken, recorded or kept here.
 */
@CapacitorPlugin(name = "RouteMakerVoiceFocus")
public class VoiceFocusPlugin extends Plugin {

    /** How long after a cue ends the music waits before coming back up. */
    static final long LET_GO_MS = 700;
    /** Longer than any cue; the turn is given back by then whatever the page does. */
    static final long MAX_HOLD_MS = 30000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable letGo = this::abandon;
    private AudioFocusRequest request;
    private boolean held;
    private final AudioManager.OnAudioFocusChangeListener listener = change -> {
        // Another app's turn (a call, another navigation app): the cue is not held over it.
        if (change == AudioManager.AUDIOFOCUS_LOSS) {
            main.post(this::abandon);
        }
    };

    @PluginMethod
    public void duck(PluginCall call) {
        main.post(() -> {
            main.removeCallbacks(letGo);
            boolean granted = held || ask();
            held = granted;
            main.postDelayed(letGo, MAX_HOLD_MS);
            JSObject answer = new JSObject();
            answer.put("ducked", granted);
            call.resolve(answer);
        });
    }

    @PluginMethod
    public void unduck(PluginCall call) {
        main.post(() -> {
            main.removeCallbacks(letGo);
            if (held) {
                main.postDelayed(letGo, LET_GO_MS);
            }
            call.resolve();
        });
    }

    @Override
    protected void handleOnDestroy() {
        main.removeCallbacks(letGo);
        abandon();
    }

    private AudioManager audio() {
        return (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
    }

    /** A short turn that lets music dip rather than stop: what navigation apps ask for. */
    private boolean ask() {
        AudioManager manager = audio();
        if (manager == null) {
            return false;
        }
        int result;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (request == null) {
                AudioAttributes attributes = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build();
                request = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                    .setAudioAttributes(attributes)
                    .setOnAudioFocusChangeListener(listener, main)
                    .build();
            }
            result = manager.requestAudioFocus(request);
        } else {
            result = manager.requestAudioFocus(listener, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK);
        }
        return result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
    }

    private void abandon() {
        main.removeCallbacks(letGo);
        if (!held) {
            return;
        }
        held = false;
        AudioManager manager = audio();
        if (manager == null) {
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && request != null) {
            manager.abandonAudioFocusRequest(request);
        } else {
            manager.abandonAudioFocus(listener);
        }
    }
}
