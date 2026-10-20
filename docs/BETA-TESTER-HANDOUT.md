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

    Address:    https://beta.example.org
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
- In Go, a press on the map, the route line included (or "Set destination at map center" in Map tools) makes that spot your destination and says "Destination set: …".
- The next thing is a link, "Skip to the route planner". It takes you past the map to the
  planner.
- The planner is an area (a landmark) called "Route planner"; screen readers may announce it
  as "Route planner, complementary". Its heading is "RouteMaker".
- In the map's bottom-left corner is a small button, "Beta notice" (it shows the word "Beta"),
  after the map's own controls. It says whether it is collapsed or expanded. Press it to open a
  region, also called "Beta notice", right after it: it says that routes may still use some
  paths where bikes are not allowed until the next map update. Press the button again, or
  Escape, to close it; the focus stays on the button. It is not shown in Ride mode.
- The "Layers" page (a button in the bar at the bottom of the planner) has one row per section:
  Traffic stress, Water and restrooms, Rail stations, Bikeshare and e-bikes, Places to see and
  Trails and terrain (and Federal land on a Mass Ride). In Plan two more follow, both off by
  default: Scenic, and DC permits (roads DDOT's work permits may close; routes never avoid them). Each row is the section's heading, a switch named for it, then a "layers" button that
  says whether it is collapsed or expanded. The switch turns the whole section on or off; off
  remembers which of its layers were on, and on brings those back. With only some on, it is on
  and says "Some on" and which. Expand a row for each layer's own switch, a one-line hint, and
  its key (what each line, color and symbol means) with the longer explanation.
- In Plan, the "Manual mode" switch in the map's bar joins each point you tap to the last by a
  straight line, for a path the planner won't take. It says when it turns on and off, and a
  "Manual mode: taps join with straight lines" label shows under the bar while it is on. Until the route comes, faint lines join
  your points: solid for legs to be routed, dashed for legs you drew. Drawn legs stay dashed on the route.
- To delete your account: Settings, Account, Delete account. The page says what is deleted and
  what is kept, and asks you to tick one box first.
- The "High contrast" switch is on the "Settings" page (the last button in the same bar). It
  makes the lines bolder and the borders and text stronger, and changes the stress colors to
  ones that do not rely on red and green.
- With the Climbs layer on (Layers), "Road info at map center" on a climb says "Climb here"
  and offers "Climb details": the climb's card, with its length, gain, grades, a described
  elevation profile and "Ride this climb". "Show climbs from" beside the switch hides the smaller
  categories.
- Ride mode (section 9) has its own heading, "Ride mode", which takes the focus when a ride
  starts. While it is on, the skip link says "Skip to ride mode" and the planner is hidden. Cues
  never move your focus: they are said through two live regions (the urgent ones, such as
  "Left now" and leaving the route, interrupt), or by RouteMaker's own voice, as you chose. With
  the focus anywhere in Ride mode, W says where you are and C puts the map back on you. "End
  ride" is a slider until you arrive: move it to the end (the arrow keys or End, or your screen
  reader's adjust gesture) to end the ride.
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

If the beta notice (the "Beta" button in the map's corner) shows a "Report a problem" link,
you can use that instead.

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
- "Where am I?" (it also re-centres the map on you) says the street you are on, the next turn and the distance to the next stop
  and the end. On a long trail away from roads it says the trail and a distance from its last
  junction, for example "On the Capital Crescent Trail, about 1.2 miles northwest of ...".
- End ride is a slide: slide it to the right to end the ride, so a bump doesn't end it. Once you
  have arrived it is a plain button. End ride and Road closed share the top row; Road closed
  always shows its words. Near sunrise or sunset, a small line under them gives the sunrise or
  sunset and civil twilight times and the minutes till each.
- After End ride you get the ride's summary: distance, moving time, average speed, total time,
  climbing and the traffic stress you rode. Done leaves Go empty for your next trip (in Plan the
  plan stays to adjust); Undo carries on with the same ride. Nothing about the ride is saved.
- Off the route for a few seconds, it says so and finds a new way from where you are. "Keep
  the planned route" says which way the route is instead.
- At Start ride the map along the route, about 1,000 ft (300 m) either side, is saved on the
  phone, so it still shows in a dead spot with no signal. A line under the buttons says what was
  saved. It lasts for this ride only: it is cleared at "End ride", when the next
  ride starts, and if you reload or reopen the page (a ride does not carry on after a reload).
  Finding a new way off the route still needs a signal.
- "Report a problem to DC 311" (Washington, DC only) writes a report for a pothole (chosen
  first), a downed tree, a vehicle parked in a bike lane, a roadway or bikeway obstructed, a
  streetlight out or anything else. The place is the road you are on, a cross street when one
  is within about 500 feet, and your GPS position, for example "on R Street Northwest near Q
  Street Northwest, Washington, DC. GPS 38.91234, -77.03890." On a
  phone, a pothole or a streetlight can be a text to DC 311 (32311) that you send yourself; the
  others go to DC 311 online, with the problem named in the report. There is always a link to
  DC 311 online and a button to copy the report for it. RouteMaker sends
  nothing and keeps nothing. Check the place before you send it.
- Your position stays on your phone. It is sent only when a new way is found from where you
  are, or when you ask for the nearest water or restroom (as "Use my location" does when
  planning), and never kept. A 311 report you send yourself carries it too. Place search, when
  the app already knows where you are and that spot is on the map you are looking at, sends an
  approximate location (about 1 km / 0.6 mi) so nearby places come first.
- Keep the screen on. If the browser cannot keep it on, Ride mode says so; on an iPhone set
  Settings, Display and Brightness, Auto-Lock to Never for the ride. In the background for more
  than 10 minutes, the ride pauses; press Resume.
- In a ride the map's street names are larger and shortened ("R St NW"), and the turn card uses fewer words ("0.2 mi", not "In 0.2 mi") so its type can be larger; a screen reader still hears the whole sentence.
- The Large text button on the ride's side (the "Aa") puts the next turn as big as it fits on the top half of the screen, with the map below, for bright sun or near sight; press it again for the normal card. "Large text during a ride" in Settings is the same switch. Ending the ride goes back to the planner.


10. Installing RouteMaker, and routes for places with no signal
---------------------------------------------------------------

RouteMaker can be installed like an app: it then opens from your home screen in its own window
(the phone's clock and battery stay in view), and it opens even with no signal.

- Android, and Chrome or Edge on a computer: press "Install RouteMaker" on the Settings page
  (also under "More tips"), then confirm in the browser's own box. If there is no such button,
  the browser's menu has "Install app" or "Add to Home screen".
- iPhone or iPad: press Share, then Add to Home Screen. Safari, Chrome and the other browsers
  there all have it. The Settings page says the same.
- The installed app may ask for the beta's user name and password once more the first time it
  opens. That is expected.
- "Keep for offline", under a route, saves the route and the map along it on this device. Open
  it again from Save & load, "Routes kept for offline", with no signal at all; the planner says it
  is the route you kept and may be out of date. "Remove" there deletes it. Up to 10 routes.
- In the installed app, the route of your last ride is kept too ("Last ride"), with the map
  saved during the ride; it is not one of the 10, and the next ride replaces it.
- Kept routes stay on this device only, until you remove them, and are never sent anywhere,
  even a route that started from "Use my location". Your position along a ride is never kept.
  In a browser tab on an iPhone, Safari may clear them after seven days without a visit; the
  installed app keeps them.
- When a new version is ready, a line at the top of the planner says "A new version of
  RouteMaker is ready." with a "Reload" button. It never interrupts a ride: it waits until you
  use "End ride". With no signal, a line there says you are offline.

11. Bike and transit together
-----------------------------

In Go, the three main buttons are "Default" (your own ride type), "Own Bike + 🚆🚌" and
"Bikeshare + 🚶🚆🚌". Cargo and plain Bikeshare are under "More ride types", where every ride
type is grouped under Transportation, Adventure or Group, with a search box over their names and
descriptions. Plan's "Change" ride type list has the same search and groups. Typing "transit",
"walk", "train" or "bus" finds both transit types. A screen reader says their names in words:
"Own bike plus train or bus" and "Bikeshare plus walk, train or bus".

- Both transit types list a few trips, quickest first. "Ride the whole way" is always one of
  them. Press a trip to put it on the map and in the steps.
- A transit trip lists its legs with their minutes: "🚶 4 min · 🚲 12 min · 🔴 18 min". 🚶 is a
  walk and 🚲 a bike. Metro shows its line's colour (🔴 Red, 🟠 Orange, 🔵 Blue, 🟢 Green, 🟡
  Yellow, ⚪ Silver), a bus its route ("🚌C53"), MARC and VRE their line ("🚆Penn",
  "🚆Fredericksburg"), Light RailLink 🚈 and Metro SubwayLink 🚇. A screen reader hears words
  instead: "walk 4 minutes, bikeshare 12 minutes, Red Line 18 minutes".
- Own Bike + 🚆🚌 takes your bike the whole way, on Metro, MARC, VRE, Light RailLink, Metro
  SubwayLink or a bus's front rack. It never asks you to leave the bike somewhere.
- Bikeshare + 🚶🚆🚌 docks the bike before you board. At each end it walks or uses a bikeshare
  bike, whichever is quicker. The docks are named. It also offers "Walk the whole way" when
  walking is quickest or the trip is under about 1 mile (1.6 km).
- The steps show each ride, walk and train or bus in order, with the total door to door. They say
  how riding the whole way compares.
- On the map, a dashed line is the ride on transit, marked with its system's name. A dotted line
  is a walk.
- All times are "about" and scheduled, from the agencies' published timetables, except on a trip
  leaving now: there a Metro train or Metrobus bus you can reach in time for is WMATA's live
  prediction and says "live". The time on board stays the timetable's.
  Weekends and holidays use their own timetables. A line with no service that day says so, for
  example "MARC Camden Line: no weekend service".
- Where trains or buses come every 15 minutes or less, the plan counts half that as the wait,
  unless a live departure times it.
  Otherwise, as on MARC, it names the departure: "MARC Penn Line 7:42 am from Union Station. You
  arrive 7:36 am (6 min spare). Next after that: 8:15 am." The same appears as a label on the map
  at the station.
- With under 5 minutes to spare, a countdown shows in the steps and on the map label. A screen
  reader hears it at 10, 5 and 2 minutes, not every second. If you would miss the departure, it
  says so and plans the next one.
- A station with no service all day is greyed and struck through on the map, named "(closed)".
  Its card says why, for example "Camden Station, closed: no MARC weekend service" (the Camden
  Line runs on weekdays only). Routes never use a closed station.
- Bikes are allowed on Metro at all hours except a few special-event days, such as July 4. On
  those days Own Bike + 🚆🚌 uses no Metro and says so: "Bikes aren't allowed on Metro today
  (July 4)." Bikeshare + 🚶🚆🚌 still uses Metro, because you walk on.
- If the beta has no timetables installed, or they have run out, Metro still runs on its typical
  timetable; the other systems wait until the timetables are rebuilt.
- In Go, More, Metro lists the three nearest Metro stations, with a badge on any that's closed.
  Elevator outages show on the station icons on the map.
- Before Metro opens, the step names the first train, for example "first train 5:00 am
  scheduled".
- Always check the agency for track work and service alerts before you go. RouteMaker does not
  see them.


12. Climbs on the map
---------------------

Turn on "Climbs" in Map layers. The number at a climb's top is its category; the shape around it
is its steepness: a circle is gentle (under 4%), a square moderate (4 to 7.9%), a diamond steep
(8% or more). "Show climbs from" hides the smaller ones. Tap a climb's top (in Go, its dashed line
too) for its card; in Plan a tap on the dashed line adds a point there as before. The card has
its length, gain, average and steepest grade and an elevation profile. "Ride this climb" puts it
in your route: in Plan its bottom and top become your next stops before the destination; in Go
the route goes to its top by way of its bottom.
