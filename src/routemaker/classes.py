"""Way classifications shared by the classifier and the tile build.

One definition, in one place. Two modules previously each declared a trail-class
set and each said in its docstring that the definition was fixed once; they
disagreed about `track`, so a rutted farm track classified as a comfortable
trail in one and as a roadway in the other.
"""

from __future__ import annotations

# Trail class, by `highway` alone and regardless of bicycle tag, because
# DC-area trails are tagged inconsistently and consulting the bicycle tag would
# classify the same trail differently along its length.
#
# `track` is deliberately absent. A track is an unpaved vehicle way, not a
# trail: it carries no separation guarantee, its ridability depends on
# `tracktype` and `smoothness`, and including it here would rate a grade5 farm
# track as comfortable for a child.
TRAIL_CLASS_HIGHWAY = frozenset({"cycleway", "footway", "path", "pedestrian", "bridleway", "steps"})

# Ways that are top-tier stress by classification alone, whatever else they are
# tagged. Named for what it asserts - a stress reading - rather than for access,
# which belongs to OSM's own `bicycle` and `access` tags and to the override
# table. `trunk` is deliberately absent: US-1, US-50 and New York Avenue NE are
# trunk here and are routinely bicycle-legal, so a blanket rule would be a
# derived access determination, which the plan reserves for an audited row. They
# reach LTS4 on their own speed and lane count anyway - which is true only
# because `trunk` and `trunk_link` are now in both default speed tables; while
# they were missing from both, an untagged one read as a 30 mph street and came
# out LTS3, and this comment was wrong about the thing it was defending. Going
# through the ordinary path also leaves their facility and shoulder tagging
# readable, which a short-circuit would discard.
ALWAYS_TOP_TIER_HIGHWAY = frozenset({"motorway", "motorway_link"})
MOTOR_ONLY_HIGHWAY = ALWAYS_TOP_TIER_HIGHWAY  # retained name for existing imports
