package org.routemaker.phone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** The first-launch screen's address check (SiteAddress): plain Java, run by `./gradlew test`. */
public class SiteAddressTest {

    private static String origin(String text) {
        SiteAddress.Parsed parsed = SiteAddress.parse(text);
        assertTrue(text + ": " + parsed.error, parsed.ok());
        assertNull(parsed.error);
        return parsed.origin;
    }

    private static String refused(String text) {
        SiteAddress.Parsed parsed = SiteAddress.parse(text);
        assertFalse(text, parsed.ok());
        assertNotNull(parsed.error);
        return parsed.error;
    }

    @Test
    public void anHttpsOriginIsKeptAsTheOriginAlone() {
        assertEquals("https://routes.example.org", origin("https://routes.example.org"));
        assertEquals("https://routes.example.org", origin("  https://Routes.Example.org/  "));
        assertEquals("https://routes.example.org", origin("routes.example.org"));
        assertEquals("https://routes.example.org", origin("HTTPS://routes.example.org:443"));
        assertEquals("https://routes.example.org:8443", origin("https://routes.example.org:8443"));
    }

    @Test
    public void onlyHttps() {
        assertTrue(refused("http://routes.example.org").contains("https://"));
        assertTrue(refused("ftp://routes.example.org").contains("https://"));
        assertTrue(refused("javascript:alert(1)").contains("https://"));
    }

    @Test
    public void notAnAddressOrMoreThanTheSite() {
        assertTrue(refused("").startsWith("Type the site's address"));
        assertTrue(refused(null).startsWith("Type the site's address"));
        refused("https://");
        refused("https://user:pw@routes.example.org");
        refused("https://routes example.org");
        assertTrue(refused("https://routes.example.org/ride").contains("alone"));
        assertTrue(refused("https://routes.example.org/?x=1").contains("alone"));
        assertTrue(refused("https://routes.example.org/#top").contains("alone"));
    }

    @Test
    public void theProbeOfHealthz() {
        assertEquals("/healthz", SiteAddress.PROBE_PATH);
        assertEquals(SiteAddress.Probe.ROUTEMAKER, SiteAddress.classify(200, "ok\n", null));
        assertEquals(SiteAddress.Probe.ROUTEMAKER_DEGRADED, SiteAddress.classify(503, "degraded\n", null));
        assertEquals(SiteAddress.Probe.PASSWORD, SiteAddress.classify(401, "", "Basic realm=\"x\""));
        assertEquals(SiteAddress.Probe.NOT_ROUTEMAKER, SiteAddress.classify(401, "", "Bearer"));
        assertEquals(SiteAddress.Probe.NOT_ROUTEMAKER, SiteAddress.classify(401, "", null));
        assertEquals(SiteAddress.Probe.NOT_ROUTEMAKER, SiteAddress.classify(200, "<!doctype html>", null));
        assertEquals(SiteAddress.Probe.NOT_ROUTEMAKER, SiteAddress.classify(301, "", null));
        assertEquals(SiteAddress.Probe.NOT_ROUTEMAKER, SiteAddress.classify(404, "Not found", null));
        assertNull(SiteAddress.refusal(SiteAddress.Probe.ROUTEMAKER));
        assertNull(SiteAddress.refusal(SiteAddress.Probe.ROUTEMAKER_DEGRADED));
        assertNull(SiteAddress.refusal(SiteAddress.Probe.PASSWORD));
        assertTrue(SiteAddress.refusal(SiteAddress.Probe.NOT_ROUTEMAKER).contains("not a RouteMaker site"));
    }
}
