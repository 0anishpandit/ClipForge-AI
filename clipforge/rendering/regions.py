"""Crop regions expressed as percentages of the source frame."""

from __future__ import annotations

from clipforge.errors import RenderError
from clipforge.utils import safe_float


def validate_region(region, label: str) -> dict:
    """Return a clean ``{"x","y","width","height"}`` dict (percent) or raise ``RenderError``."""
    if not isinstance(region, dict):
        raise RenderError(f"Please configure the {label} region.")

    x = safe_float(region.get("x"))
    y = safe_float(region.get("y"))
    width = safe_float(region.get("width"))
    height = safe_float(region.get("height"))
    if None in (x, y, width, height):
        raise RenderError(f"The {label} region has invalid values.")

    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 100 or y + height > 100:
        raise RenderError(f"The {label} region must fit inside the source video.")

    return {"x": x, "y": y, "width": width, "height": height}


def region_crop_filter(region, label: str = "video") -> str:
    """FFmpeg ``crop=`` expression for a percentage region."""
    r = validate_region(region, label)
    return (
        f"crop=iw*{r['width'] / 100:.6f}:ih*{r['height'] / 100:.6f}:"
        f"iw*{r['x'] / 100:.6f}:ih*{r['y'] / 100:.6f}"
    )


def default_gameplay_region(facecam_region: dict | None = None) -> dict:
    """Compute a clean default gameplay region covering the full frame (or avoiding facecam)."""
    return {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0}
