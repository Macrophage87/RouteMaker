package org.routemaker.phone;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.speech.RecognizerIntent;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.ArrayList;

/**
 * Speak, in Send alert's Other box (frontend/src/lib/speechInput.ts; Stephen 2026-10-30, "Enable text to speech on
 * an android app"). Android's WebView has no speech recognition, so the page hands the language here and Android's
 * own speech input (Google's on most phones) opens over the app, listens once, and gives the words back. That app
 * has the microphone, not RouteMaker, so the manifest asks for no RECORD_AUDIO. The words go only to the page's
 * box; nothing is kept here and nothing is sent until the rider taps Send.
 */
@CapacitorPlugin(name = "RouteMakerSpeech")
public class SpeechPlugin extends Plugin {

    /** Longer than any alert's Other box (80 characters); the page cuts to its own limit. */
    static final int MAX_CHARS = 500;

    @PluginMethod
    public void listen(PluginCall call) {
        String lang = call.getString("lang", "");
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        if (langOk(lang)) {
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
        }
        try {
            startActivityForResult(call, intent, "heard");
        } catch (ActivityNotFoundException | SecurityException e) {
            call.reject("No speech input on this phone", "unavailable", e);
        }
    }

    @ActivityCallback
    private void heard(PluginCall call, ActivityResult result) {
        if (call == null) {
            return;
        }
        int code = result.getResultCode();
        if (code == Activity.RESULT_OK) {
            Intent data = result.getData();
            ArrayList<String> said = data == null ? null : data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
            JSObject words = new JSObject();
            words.put("text", first(said));
            call.resolve(words);
            return;
        }
        String failed = failure(code);
        if (failed == null) {
            // Backed out of the speech input: nothing heard, nothing to say.
            JSObject words = new JSObject();
            words.put("text", "");
            call.resolve(words);
            return;
        }
        call.reject("Speech did not work", failed);
    }

    /** A BCP 47 tag of the shape the site sends ("en-US", "es"), nothing else. */
    static boolean langOk(String lang) {
        return lang != null && lang.matches("[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}");
    }

    /** The best guess, cut to a sensible length; empty when there is none. */
    static String first(ArrayList<String> said) {
        if (said == null || said.isEmpty() || said.get(0) == null) {
            return "";
        }
        String text = said.get(0).trim();
        return text.length() > MAX_CHARS ? text.substring(0, MAX_CHARS) : text;
    }

    /** The page's failure code (speechInput.ts SPEECH_FAILED) for a recognizer's result code; null for a back-out. */
    static String failure(int code) {
        switch (code) {
            case RecognizerIntent.RESULT_NO_MATCH:
                return "no-speech";
            case RecognizerIntent.RESULT_NETWORK_ERROR:
            case RecognizerIntent.RESULT_SERVER_ERROR:
                return "network";
            case RecognizerIntent.RESULT_AUDIO_ERROR:
                return "audio-capture";
            case RecognizerIntent.RESULT_CLIENT_ERROR:
                return "other";
            default:
                return null;
        }
    }
}
