For the sender (do not send this part)
=====================================

- Send everything below the cut line, as it is: plain text in the body of a message, or as a
  .txt file. Fill in the user name and password lines for each person first.
- Send the user name and password as text the tester can copy. Not by voice, not in an image
  or screenshot, and never as a link with the password in it (https://name:password@...):
  many browsers block or warn about those, and they end up in history.
- The passwords are in the file make-htpasswd.sh wrote (docs/BETA-RUNBOOK.md, step 9a). Delete
  that file (shred -u) once every tester has theirs.
- Section 8 (Updates) gives no hours. If the beta's agent has an update window
  (RM_CD_WINDOW in the server's vars.sh), you may add a sentence there with those hours, for
  example "Updates usually happen between 2 and 6 in the morning, Eastern time." Without
  one, updates can come at any hour, so do not promise nights.

---------------------------- cut here: send everything below ----------------------------

RouteMaker beta: how to get in
==============================

    Address:    https://routemaker.cieply.com
    User name:  (filled in by whoever gives you access)
    Password:   (sent with it, as text you can copy)

RouteMaker plans bike routes for the DC region and Baltimore. This is a private test version
for friends and family, so it asks for a password before it shows anything.


1. Open it in a real browser
----------------------------

Use Safari, Chrome, Firefox or Edge itself. Do not open the link from inside a messaging or
mail app (Messages, WhatsApp, Discord, Messenger, Gmail and the like): their built-in
browsers often cannot show the sign-in box and forget saved passwords. If you tapped the link
there, choose "Open in browser", or copy the address into your browser.


2. The sign-in box is your browser's own
----------------------------------------

Before any page appears, your browser shows a small box asking for a user name and a
password. It comes from the browser, not from RouteMaker, and it may not mention RouteMaker
at all. With a screen reader, focus is normally already in the user name field.


3. Type the user name exactly
-----------------------------

The user name is case-sensitive. It is all lowercase, exactly as it was given to you.


4. Paste the password, and save it
----------------------------------

Copy the password from the message and paste it rather than typing it. It is four groups of
five lowercase letters and digits joined by dashes, and the dashes are part of it. It never
uses the characters l, 1, o, 0 or i, so nothing in it looks like something else. When your
browser or password manager offers to save it, say yes: next time it fills in for you.


5. A wrong password just shows the box again
--------------------------------------------

There is no error message. If the box comes back, check that the user name is all lowercase
and paste the password again. If you press Cancel, you get a short page that says sign-in is
needed; reload the page to get the box back.


6. Once you are in (for screen-reader users)
--------------------------------------------

- The first thing on the page is a button, "Accessibility mode", a switch that starts off.
  Turn it on to get Map tools by the map's zoom buttons, with "Add point at map center" and
  "Road info at map center". It stays on for this device. The same switch is in "More tips".
- The next thing is a link, "Skip to the route planner". It takes you past the map to the
  planner.
- The planner is an area (a landmark) called "Route planner"; screen readers may announce it
  as "Route planner, complementary". Its heading is "RouteMaker".
- Just under that heading is a region called "Beta notice", with a "Dismiss" button. It says
  that routes may still use some paths where bikes are not allowed until the next map update.
  Dismiss hides it until your next visit and puts you back at the planner.
- The "High contrast" switch is in two places: the "Map layers" page (a button in the bar at
  the bottom of the planner) and the "Settings" page (the last button in the same bar). It makes the lines bolder
  and the borders and text stronger, and changes the stress colors to ones that do not rely
  on red and green. Both switches are the same setting.
- Ride mode (section 9) has its own heading, "Ride mode", which takes the focus when a ride
  starts. While it is on, the skip link says "Skip to ride mode" and the planner is hidden. Cues
  never move your focus: they are said through two live regions (the urgent ones, such as
  "Left now" and leaving the route, interrupt), or by RouteMaker's own voice, as you chose. With
  the focus anywhere in Ride mode, W says where you are and C puts the map back on you.
- Installing and offline (section 10): "Install the app" and "Routes kept for offline" are
  headings on the Settings page. Each kept route has an "Open" and a "Remove" button that name
  the route. Remove says what it removed and puts the focus on the next route's Remove, or on
  the heading when none is left. "A new version of RouteMaker is ready" and "You are offline"
  are said once, politely, and never move your focus.


7. Reporting a problem
----------------------

Tell the person who gave you access. It helps to include:

- the page's address, copied from the address bar after you planned the route (it holds your
  points, so it reopens the same route);
- what you expected, and what happened instead;
- the browser and device, and the screen reader if you use one.

If the beta notice shows a "Report a problem" link, you can use that instead.

8. Updates
----------

Now and then the beta is updated to a new version. For about 10 to 20 minutes the page still
opens, but planning a route says "Router unavailable", place search and the road information
say they are "not available right now", and Sign in shows a "Back soon" or "502 Bad Gateway"
page (the browser's Back button takes you back to your route). That is the update, not something you did.
Wait about 20 minutes and try again. Report it only if it lasts more than half an hour.


9. Ride mode: directions while you ride
---------------------------------------

For short rides, up to 30 miles (48 km), on a phone with the screen on and the page in front.
For longer rides, use Download GPX with a bike computer, which keeps going with the screen off.
You stay responsible for riding safely; the route can be wrong.

- Plan a route, then press "Start ride", under the route's figures or in Directions. The
  browser asks to use your location.
- The first time, it asks how to say the cues: with your screen reader, RouteMaker's voice,
  both, or neither (on screen only), and how much: Full (every turn, early and again close to
  it), Stoker (each turn once ahead and as it happens, busy crossings and stops: for the rider
  behind on a tandem) or Quiet (only arrival). Both choices stay on this device; change them in
  "Ride settings" during a ride, or in Settings.
- "Where am I?" says the street you are on, the next turn and the distance to the next stop
  and the end. On a long trail away from roads it says the trail and a distance from its last
  junction, for example "On Capital Crescent Trail, about 1.2 miles northwest of ...".
- Off the route for a few seconds, it says so and finds a new way from where you are. "Keep
  the planned route" says which way the route is instead.
- At Start ride the map along the route (about 1,000 feet, 300 m, either side) is saved on the phone,
  so it still shows in a dead spot with no signal. It is cleared when you press "End ride".
  Finding a new way off the route still needs a signal.
- "Report a problem to DC 311" (Washington, DC only) writes a report for a pothole, a
  streetlight out or anything else, with the nearest junction on your route as the place. On a
  phone, a pothole or a streetlight opens a text to DC 311 (32311) that you send yourself;
  anything else, and everything on a computer, is text to copy into DC 311 online. RouteMaker
  sends nothing and keeps nothing. Check the place before you send it.
- Your position stays on your phone. It is sent only when a new way is found from where you
  are, or when you ask for the nearest water or restroom (as "Use my location" does when
  planning), and never kept.
- Keep the screen on. If the browser cannot keep it on, Ride mode says so; on an iPhone set
  Settings, Display and Brightness, Auto-Lock to Never for the ride. In the background for more
  than 10 minutes, the ride pauses; press Resume.
- "Big text" hides the map and shows the next cue large. "End ride" goes back to the planner.


10. Installing RouteMaker, and routes for places with no signal
---------------------------------------------------------------

RouteMaker can be installed like an app: it then opens from your home screen in its own window
(the phone's clock and battery stay in view), and it opens even with no signal.

- Android, and Chrome or Edge on a computer: press "Install RouteMaker" on the Settings page
  (also under "More tips"), then confirm in the browser's own box. If there is no such button,
  the browser's menu has "Install app" or "Add to Home screen".
- iPhone or iPad: in Safari, press Share, then Add to Home Screen. The Settings page says the
  same.
- The installed app may ask for the beta's user name and password once more the first time it
  opens. That is expected.
- "Keep for offline", under a route, saves the route and the map along it on this device. Open
  it again from Settings, "Routes kept for offline", with no signal at all; the planner says it
  is the route you kept and may be out of date. "Remove" there deletes it. Up to 10 routes.
- In the installed app, the route of your last ride is kept too ("Last ride"), with the map
  saved during the ride, and the next ride replaces it.
- Kept routes stay on this device only, until you remove them, and are never sent anywhere,
  even a route that started from "Use my location". Your position along a ride is never kept.
  In a browser tab on an iPhone, Safari may clear them after seven days without a visit; the
  installed app keeps them.
- When a new version is ready, a line at the top of the planner says "A new version of
  RouteMaker is ready." with a "Reload" button. It never interrupts a ride: it waits until you
  press "End ride". With no signal, a line there says you are offline.
