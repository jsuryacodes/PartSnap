"""Fix-type registry. Each module exposes PARAMS, make(), expected_bbox(), mating_solid()."""
from . import corner_cap

FIXES = {"corner_cap": corner_cap}
