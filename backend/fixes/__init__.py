"""Fix-type registry. Each module exposes PARAMS, make(), expected_bbox(), mating_solid().
Optional: outlines_mm() (shape from the photos), SANDBOX (helper names the agent's code may call in verify),
MIN_THICKNESS + thickness_profile() (min-thickness check), BBOX_HINTS (wording for bbox failures)."""
from . import chip_fill, corner_cap

FIXES = {"chip_fill": chip_fill, "corner_cap": corner_cap}  # chip_fill is the default for chipped corners/edges
