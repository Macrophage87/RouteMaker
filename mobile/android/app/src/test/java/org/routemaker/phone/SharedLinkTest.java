package org.routemaker.phone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

public class SharedLinkTest {

    private static final String SITE = "https://routes.example.org";

    @Test
    public void takesALinkToTheKeptSiteWithItsRoute() {
        String link = "https://routes.example.org/#p=-77.04000,38.91000;-77.01000,38.89000&preset=bikeshare&v=2";
        assertEquals(link, SharedLink.find(link, SITE));
    }

    @Test
    public void takesTheLinkOutOfASentence() {
        assertEquals("https://routes.example.org/?r=abc", SharedLink.find("Ride with me: https://routes.example.org/?r=abc.", SITE));
        assertEquals("https://Routes.Example.org/x", SharedLink.find("(https://Routes.Example.org/x)", SITE));
    }

    @Test
    public void refusesAnotherSite() {
        assertNull(SharedLink.find("https://evil.example.com/#p=1", SITE));
        assertNull(SharedLink.find("https://routes.example.org.evil.com/", SITE));
        assertNull(SharedLink.find("https://user@routes.example.org/", SITE));
        assertNull(SharedLink.find("https://routes.example.org:8443/", SITE));
    }

    @Test
    public void refusesPlainHttpAndNoLink() {
        assertNull(SharedLink.find("http://routes.example.org/", SITE));
        assertNull(SharedLink.find("no link here", SITE));
        assertNull(SharedLink.find(null, SITE));
        assertNull(SharedLink.find("", SITE));
    }
}
