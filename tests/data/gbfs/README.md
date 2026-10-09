# GBFS test sample

A small sanitized sample of the bikeshare operator's official GBFS feeds, taken on
2026-10-04 (GBFS 1.1, ttl 60 s): 27 stations near Union Station and Dupont Circle, their
statuses, 50 free-floating e-bikes, the pricing plans and the alerts, with the discovery
feed. Station and bike ids are replaced, and the fields RouteMaker does not read
(rental links, kiosk and key fields) are dropped.

This is a test sample, not a dataset (OWNER-DECISIONS 300: the data licence forbids hosting
or distributing the data as a stand-alone dataset, and data mining). It is used only by
`tests/test_gbfs.py`, `tests/test_bikeshare.py` and `tests/test_bikeshare_api.py`. Do not
enlarge it, refresh it in bulk or ship it with the application.

What the operator publishes, as of the sample: no `geofencing_zones` feed; one pricing
plan, the e-bike single ride, which names no out-of-dock fee.

Two of the sampled stations had been silent for hours when the sample was taken (their
`last_reported` is 3.7 and 8.5 hours before the newest). Tests read the sample as of
`FEED_NOW` in `tests/test_gbfs.py` (a few seconds after the newest report), never as of
today, so those two stay "not reported in 30 minutes" whenever the suite runs.
