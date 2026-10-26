For the sender (do not send this part)
=====================================

- Send everything below the cut line, as it is: plain text in the body of a message, or as a
  .txt file. Put the beta's address in the Address line first.
- The beta has no site password (the owner's call, 2026-10-22), so there is nothing else to
  send: no user name, no password.
- Section 4 (Updates) gives no hours. If the beta's agent has an update window
  (RM_CD_WINDOW in the server's vars.sh), you may add a sentence there with those hours, for
  example "Updates usually happen between 2 and 6 in the morning, Eastern time." Without
  one, updates can come at any hour, so do not promise nights.

---------------------------- cut here: send everything below ----------------------------

RouteMaker beta: how to get in
==============================

    Address:    https://beta.example.org

RouteMaker plans bike routes for the DC region and Baltimore. This is a test version, so
some things may be rough or change; nothing asks for a password.


1. Open it in a real browser
----------------------------

Use Safari, Chrome, Firefox or Edge itself. Do not open the link from inside a messaging or
mail app (Messages, WhatsApp, Discord, Messenger, Gmail and the like): their built-in
browsers often cannot sign you in, install the app or keep routes for offline. If you tapped
the link there, choose "Open in browser", or copy the address into your browser.

You don't need an account to plan or ride. Signing in (with Discord) is only for saving
routes and keeping your 311 checklist on your other devices.


2. Once you are in (for screen-reader users)
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
  paths where bikes are not allowed until the next map update, then links our Discord for
  reports and has a small "Sign up to test here!" link. Press the button again, or
  Escape, to close it; the focus stays on the button. It is not shown in Ride mode.
- The "Layers" page (a button in the bar at the bottom of the planner) has one row per section:
  Traffic stress, Water and restrooms, Rail stations, Bikeshare and e-bikes, Places to see and
  Trails and terrain (and Federal land on a Mass Ride). In Plan two more follow, both off by
  default: Scenic, and DC permits (roads DDOT's work permits may close; routes never avoid them). Each row is the section's heading, a switch named for it, then a "layers" button that
  says whether it is collapsed or expanded. The switch turns the whole section on or off; off
  remembers which of its layers were on, and on brings those back. With only some on, it is on
  and says "Some on" and which. Expand a row for each layer's own switch, a one-line hint, and
  its key (what each line, color and symbol means) with the longer explanation.
- Plan starts as a loop: the "Loop" box is ticked, so each point after the start is a stop and the
  ride comes back. To finish somewhere else, untick it, choose "Make this the destination" under a
  search result, or right-click the map (press and hold on a phone) and choose "Set as end" ("End
  here" on a station's card): the loop turns off and says so.
  With no points yet, "Start at current location" sits where the "Route" button goes.
- In Plan, the "Manual mode" switch in the map's bar joins each point you tap to the last by a
  straight line, for a path the planner won't take; turned on during a loop, it turns the loop off.
  It says when it turns on and off, and a "Manual mode: taps join with straight lines" label shows
  under the bar while it is on. Until the route comes, bold lines with arrows join your points in
  the order you'll ride them (a loop's way back to the start too): solid for legs to be routed,
  dashed for legs you drew. Drag a line to add a via point in that leg. Drawn legs stay dashed on the route.
- To delete your account: Settings, Account, Delete account. The page says what is deleted and
  what is kept, and asks you to tick one box first.
- The "High contrast" switch is on the "Settings" page (the last button in the same bar). It
  makes the lines bolder and the borders and text stronger, and changes the stress colors to
  ones that do not rely on red and green.
- With the Climbs layer on (Layers), "Road info at map center" on a climb says "Climb here"
  and offers "Climb details": the climb's card, with its length, gain, grades, a described
  elevation profile and "Ride this climb". "Show climbs from" beside the switch hides the smaller
  categories.
- Ride mode (section 5) has its own heading, "Ride mode", which takes the focus when a ride
  starts. While it is on, the skip link says "Skip to ride mode" and the planner is hidden. Cues
  never move your focus: they are said through two live regions (the urgent ones, such as
  "Left now" and leaving the route, interrupt), or by RouteMaker's own voice, as you chose. With
  the focus anywhere in Ride mode, W says where you are and C puts the map back on you. "End
  ride" is a slider until you arrive: move it to the end (the arrow keys or End, or your screen
  reader's adjust gesture) to end the ride.
- Installing and offline (section 6): "Install the app" and "Routes kept for offline" are
  headings on the Settings page. Each kept route has an "Open" and a "Remove" button that name
  the route. Remove says what it removed and puts the focus on the next route's Remove, or on
  the heading when none is left. "A new version of RouteMaker is ready" and "You are offline"
  are said once, politely, and never move your focus.


3. Reporting a problem
----------------------

Tell the person who gave you access. It helps to include:

- the page's address, copied from the address bar after you planned the route (it holds your
  points, so it reopens the same route);
- what you expected, and what happened instead;
- the browser and device, and the screen reader if you use one.

Or tell us on Discord: the beta notice (the "Beta" button in the map's corner) links the
invite. If it also shows a "Report a problem" link, you can use that instead.

4. Updates
----------

Now and then the beta is updated to a new version. For about 10 to 20 minutes the page still
opens, but planning a route says "Router unavailable", place search and the road information
say they are "not available right now", and Sign in shows a "Back soon" or "502 Bad Gateway"
page (the browser's Back button takes you back to your route). That is the update, not something you did.
Wait about 20 minutes and try again. Report it only if it lasts more than half an hour.


5. Ride mode: directions while you ride
---------------------------------------

For short rides, up to 30 miles (48 km), on a phone with the screen on and the page in front.
For longer rides, use Download GPX with a bike computer, which keeps going with the screen off.
You stay responsible for riding safely; the route can be wrong.

- Plan a route, then press "Start ride", on the bar at the top of the map (once you've picked a
  route), under the route's figures or in Directions. The
  browser asks to use your location.
- The ride starts at once. The cues use your Settings (Riding): who says them, your screen
  reader, RouteMaker's voice, both, or neither (on screen only), and how much: Full (every turn,
  early and again close to it), Stoker (each turn once ahead and as it happens, busy crossings and
  stops: for the rider behind on a tandem) or Quiet (only arrival). Until you change them,
  RouteMaker's voice says every turn. Both choices stay on this device; change them in
  the ride's More panel (the last side button) during a ride, or in Settings.
- Under the turn, the ride shows the distance and time to the next stop and to the end, and the clock time you
  should get there ("8 min · 6:42 AM"). Once you have ridden about half a mile the times follow your own pace, not
  only the route's; a long stop on the way does not count against you.
- "Where am I?" (it also re-centres the map on you) says the street you are on, the next turn and the distance to the next stop
  and the end, with the time you should arrive at each. On a long trail away from roads it says the trail and a distance from its last
  junction, for example "On the Capital Crescent Trail, about 1.2 miles northwest of ...".
- Moved the map by hand? Leave the screen alone for 30 seconds and the map goes back to following
  you, at the ride's usual zoom. Map cards, road info and the side menus close on their own after
  the same 30 seconds, unless you are typing in one or accessibility mode is on.
- End ride is a slide: slide it to the right to end the ride, so a bump doesn't end it. Once you
  have arrived it is a plain button. End ride and Road closed share the top row; Road closed
  always shows its words. Near sunrise or sunset, a small line under them gives the sunrise or
  sunset and civil twilight times and the minutes till each.
- After End ride you get the ride's summary: distance, moving time, average speed, total time,
  climbing, an elevation chart and the traffic stress you rode. Done leaves Go empty for your next trip (in Plan the
  plan stays to adjust); Undo carries on with the same ride. Nothing about the ride is saved.
- Off the route for a few seconds, it says so and finds a new way from where you are. "Keep
  the planned route" says which way the route is instead.
- At Start ride the map along the route, about 1,000 ft (300 m) either side, is saved on the
  phone, so it still shows in a dead spot with no signal. A line under the buttons says what was
  saved. It lasts for this ride only: it is cleared at "End ride", when the next
  ride starts, and if you reload or reopen the page (a ride does not carry on after a reload).
  Finding a new way off the route still needs a signal.
- The round 311 button logs a problem where you are, anywhere on the route: a pothole, a
  downed tree, a vehicle parked in a bike lane, a roadway or bikeway obstructed, a streetlight
  out or something else. The entry keeps the road you are on, a cross street when one is within
  about 500 feet, your GPS position and the time, for example "on R Street Northwest near Q
  Street Northwest. GPS 38.91234, -77.03890." One tap logs it; the menu shows all six at once,
  and there is no note to type while riding. Off a ride, right-click a road on the map (press
  and hold on a phone) and choose Log for 311.
- Your 311 checklist is in Reports (Go's Menu, or Plan's bottom bar; it was called Suggest). It
  lists what you logged under the website that takes it (DC 311, MC311, PGC311, Baltimore 311,
  Arlington, Alexandria, VDOT and the rest), each with when you logged it and Copy report. Paste
  the report into the site, then check the entry off and it moves to Archived, with when you
  reported it. One left unchecked for 30 days moves to Archived by itself, marked not reported;
  nothing is deleted. When you end a ride with problems still to report, the ride's summary says
  how many and has Open Reports. Texting DC 311 (32311) is gone: DC's text line answers
  only "Welcome to DC311". Signed in, the checklist follows you to your other devices; signed
  out, it is this device's own, and what you logged signed out joins your account when you sign
  in. Where the server can send DC reports itself, a DC problem is sent at once and goes straight
  to Archived.
- Your position stays on your phone. It is sent only when a new way is found from where you
  are, or when you ask for the nearest water or restroom (as "Use my location" does when
  planning), and never kept. A problem you log for 311 keeps it, on your phone and, signed in,
  with your account; outside DC the app asks the server which county's website takes it. Place search, when
  the app already knows where you are and that spot is on the map you are looking at, sends an
  approximate location (about 1 km / 0.6 mi) so nearby places come first.
- Keep the screen on. If the browser cannot keep it on, Ride mode says so; on an iPhone set
  Settings, Display and Brightness, Auto-Lock to Never for the ride. In the background for more
  than 10 minutes, the ride pauses; press Resume.
- In a ride the map's street names are larger and shortened ("R St NW") and come before shop names, place names and the water, restroom and repair icons (station names and hazard marks still come first), so far more of the streets near you keep their names (drawn over the route too), and the turn card uses fewer words ("0.2 mi", not "In 0.2 mi") so its type can be larger; a screen reader still hears the whole sentence.
- The Large text button on the ride's side (the "Aa") puts the next turn as big as it fits on the top half of the screen, with the map below, for bright sun or near sight; press it again for the normal card. "Large text during a ride" in Settings is the same switch. Ending the ride goes back to the planner.


6. Installing RouteMaker, and routes for places with no signal
--------------------------------------------------------------

RouteMaker can be installed like an app: it then opens from your home screen in its own window
(the phone's clock and battery stay in view), and it opens even with no signal.

- Android, and Chrome or Edge on a computer: press "Install RouteMaker" on the Settings page
  (also under "More tips"), then confirm in the browser's own box. If there is no such button,
  the browser's menu has "Install app" or "Add to Home screen".
- iPhone or iPad: press Share, then Add to Home Screen. Safari, Chrome and the other browsers
  there all have it. The Settings page says the same.
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

7. Bike and transit together
----------------------------

In Go, the three main buttons are "Default" (your own ride type), "Own Bike + 🚆🚌" and
"Bikeshare + 🚶🚆🚌". Cargo and plain Bikeshare are under "More ride types", where every ride
type is grouped under Transportation, Adventure or Group, with a search box over their names and
descriptions. Plan's "Change" ride type list has the same search and groups. Typing "transit",
"walk", "train" or "bus" finds both transit types. A screen reader says their names in words:
"Own bike plus train or bus" and "Bikeshare plus walk, train or bus".

- Both transit types list a few trips. Bikeshare plus transit lists the quickest first. Own bike
  plus transit lists the best first: time to get there, with time on busy roads and waiting at
  junctions counting against a trip, so each trip says how far it rides on busy roads ("0.4 mi
  (0.6 km) busy"), which explains a list out of time order. "Ride the whole way" is always one of
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


8. Climbs on the map
--------------------

Turn on "Climbs" in Map layers. The number at a climb's top is its category; the shape around it
is its steepness: a circle is gentle (under 4%), a square moderate (4 to 7.9%), a diamond steep
(8% or more). "Show climbs from" hides the smaller ones. Tap a climb's top (in Go, its dashed line
too) for its card; in Plan a tap on the dashed line adds a point there as before. The card has
its length, gain, average and steepest grade and an elevation profile. "Ride this climb" puts it
in your route: in Plan its bottom and top become your next stops before the destination; in Go
the route goes to its top by way of its bottom.
