For the sender (do not send this part)
=====================================

- Send everything below the cut line, as it is: plain text in the body of a message, or as a
  .txt file. Fill in the user name and password lines for each person first.
- Send the user name and password as text the tester can copy. Not by voice, not in an image
  or screenshot, and never as a link with the password in it (https://name:password@...):
  many browsers block or warn about those, and they end up in history.
- The passwords are in the file make-htpasswd.sh wrote (docs/BETA-RUNBOOK.md, step 9a). Delete
  that file (shred -u) once every tester has theirs.

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

- The first thing on the page is a link, "Skip to the route planner". It takes you past the
  map to the planner.
- The planner is an area (a landmark) called "Route planner"; screen readers may announce it
  as "Route planner, complementary". Its heading is "RouteMaker".
- Just under that heading is a region called "Beta notice", with a "Dismiss" button. It says
  that routes may still use some paths where bikes are not allowed until the next map update.
  Dismiss hides it until your next visit and puts you back at the planner.
- The "High contrast" switch is in two places: the "Map layers" page (a button in the bar at
  the bottom of the planner) and the "Settings" page next to it. It makes the lines bolder
  and the borders and text stronger, and changes the stress colors to ones that do not rely
  on red and green. Both switches are the same setting.


7. Reporting a problem
----------------------

Tell the person who gave you access. It helps to include:

- the page's address, copied from the address bar after you planned the route (it holds your
  points, so it reopens the same route);
- what you expected, and what happened instead;
- the browser and device, and the screen reader if you use one.

If the beta notice shows a "Report a problem" link, you can use that instead.
