package org.routemaker.phone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** What the share sheet takes: a web link only, and the text with the link on its own line. */
public class SharePluginTest {

    @Test
    public void aWebLinkIsShared() {
        assertTrue(SharePlugin.linkOk("https://example.org/#p=-77.03650,38.89770;-77.00900,38.88990&ride=1"));
        assertTrue(SharePlugin.linkOk("http://localhost:8080/#p=1,2;3,4"));
    }

    @Test
    public void anythingElseIsRefused() {
        assertFalse(SharePlugin.linkOk(null));
        assertFalse(SharePlugin.linkOk(""));
        assertFalse(SharePlugin.linkOk("javascript:alert(1)"));
        assertFalse(SharePlugin.linkOk("file:///data/data/org.routemaker.phone/shared_prefs/site.xml"));
        assertFalse(SharePlugin.linkOk("https://" + "a".repeat(SharePlugin.MAX_CHARS)));
    }

    @Test
    public void theLinkGoesOnItsOwnLine() {
        assertEquals("2.9 mi (4.7 km) bike route.\nhttps://example.org/", SharePlugin.body("2.9 mi (4.7 km) bike route.", "https://example.org/"));
        assertEquals("https://example.org/", SharePlugin.body("", "https://example.org/"));
    }
}
