package org.routemaker.phone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

/** The names Send to Garmin's file may have: a plain course file name, never a path. */
public class FilesPluginTest {

    @Test
    public void aCourseFileNameIsKept() {
        assertEquals("routemaker-default-1_9mi.fit", FilesPlugin.safeName("routemaker-default-1_9mi.fit"));
        assertEquals("ride.tcx", FilesPlugin.safeName("ride.tcx"));
        assertEquals("ride.gpx", FilesPlugin.safeName("ride.gpx"));
        assertEquals("routemaker-default-1_9mi-cues.pdf", FilesPlugin.safeName("routemaker-default-1_9mi-cues.pdf"));
        assertEquals("routemaker-default-1_9mi-lock-1-of-3.png", FilesPlugin.safeName("routemaker-default-1_9mi-lock-1-of-3.png"));
    }

    @Test
    public void anythingElseIsRefused() {
        assertNull(FilesPlugin.safeName(null));
        assertNull(FilesPlugin.safeName("../shared_prefs/site.fit"));
        assertNull(FilesPlugin.safeName("courses/ride.fit"));
        assertNull(FilesPlugin.safeName(".fit"));
        assertNull(FilesPlugin.safeName("ride.html"));
        assertNull(FilesPlugin.safeName("ride.fit.html"));
        assertNull(FilesPlugin.safeName("ride.svg"));
        assertNull(FilesPlugin.safeName("ride .fit"));
        assertNull(FilesPlugin.safeName("a".repeat(118) + ".fit"));
    }
}
