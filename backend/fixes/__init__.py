"""Fix-type registry. Each module exposes PARAMS, make(), expected_bbox(), mating_solid().
Optional: OUTLINES + outlines_mm() (shape from the photos), missing_solid() (enables the fill-ratio check),
MIN_FEATURE (features under it are flattened, so local gaps may exceed the clearance)."""
from . import chip_fill, corner_cap

FIXES = {"chip_fill": chip_fill, "corner_cap": corner_cap}  # chip_fill is the default for chipped corners/edges
