package org.routemaker.phone;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import android.media.AudioManager;
import org.junit.Test;

public class RideCuePluginTest {
    @Test
    public void eachArrowWordHasItsDrawable() {
        assertEquals("rm_arrow_left", RideCuePlugin.arrowIcon("left"));
        assertEquals("rm_arrow_right", RideCuePlugin.arrowIcon("right"));
        assertEquals("rm_arrow_bear_left", RideCuePlugin.arrowIcon("bear_left"));
        assertEquals("rm_arrow_bear_right", RideCuePlugin.arrowIcon("bear_right"));
        assertEquals("rm_arrow_uturn", RideCuePlugin.arrowIcon("uturn"));
        assertEquals("rm_arrow_flag", RideCuePlugin.arrowIcon("end"));
        assertEquals("ic_ride", RideCuePlugin.arrowIcon("straight"));
        assertEquals("ic_ride", RideCuePlugin.arrowIcon(null));
    }

    @Test
    public void leftAndRightBuzzDifferentlyAndNothingElseBuzzes() {
        assertArrayEquals(RideCuePlugin.LEFT, RideCuePlugin.pattern("left"));
        assertArrayEquals(RideCuePlugin.RIGHT, RideCuePlugin.pattern("right"));
        assertNotEquals(RideCuePlugin.LEFT.length, RideCuePlugin.RIGHT.length);
        assertNull(RideCuePlugin.pattern("off"));
        assertNull(RideCuePlugin.pattern(null));
    }

    @Test
    public void aSilentPhoneGetsNoBuzz() {
        assertFalse(RideCuePlugin.buzzAllowed(AudioManager.RINGER_MODE_SILENT));
        assertTrue(RideCuePlugin.buzzAllowed(AudioManager.RINGER_MODE_VIBRATE));
        assertTrue(RideCuePlugin.buzzAllowed(AudioManager.RINGER_MODE_NORMAL));
    }

    @Test
    public void offRouteHasItsOwnTone() {
        assertEquals(1, RideCuePlugin.beeps("turn"));
        assertEquals(2, RideCuePlugin.beeps("off"));
        assertEquals(210, RideCuePlugin.chimeMs("turn"));
        assertEquals(290, RideCuePlugin.chimeMs("off"));
    }
}
