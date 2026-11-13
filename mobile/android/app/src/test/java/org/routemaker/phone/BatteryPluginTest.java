package org.routemaker.phone;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class BatteryPluginTest {
    @Test
    public void knownStrictMakersAreNamedWhateverTheirCase() {
        assertTrue(BatteryPlugin.strictMaker("samsung"));
        assertTrue(BatteryPlugin.strictMaker("Xiaomi"));
        assertTrue(BatteryPlugin.strictMaker(" OnePlus "));
    }

    @Test
    public void otherMakersAndNothingAreNot() {
        assertFalse(BatteryPlugin.strictMaker("Google"));
        assertFalse(BatteryPlugin.strictMaker(""));
        assertFalse(BatteryPlugin.strictMaker(null));
    }
}
