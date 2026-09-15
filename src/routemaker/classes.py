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

# Ways a bicycle may not use. An access question, not a comfort question.
MOTOR_ONLY_HIGHWAY = frozenset({"motorway", "motorway_link", "trunk", "trunk_link"})
