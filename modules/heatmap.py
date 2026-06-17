from __future__ import annotations

import functools
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import matplotlib as mpl
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    import numpy as np

AVAILABLE: bool = False
_SLOTS_PER_DAY = 288  # 5-minute buckets

try:
    import matplotlib as mpl
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    import numpy as np

    AVAILABLE = True
except ImportError:
    pass


@functools.cache
def _get_cmap() -> mcolors.LinearSegmentedColormap:
    rocket = mpl.colormaps["magma"]
    black = [(0.0, 0.0, 0.0, 1.0)] * 10
    gradient = [rocket(i / 300) for i in range(300)]
    cyan = [(0.0, 1.0, 1.0, 1.0)] * 10
    return mcolors.LinearSegmentedColormap.from_list("heatmap", black + gradient + cyan)


def _gaussian_blur(grid: np.ndarray, sigma_rows: float, sigma_cols: float) -> np.ndarray:
    def _kernel(sigma: float) -> np.ndarray:
        r = max(1, round(sigma * 3))
        x = np.arange(-r, r + 1, dtype=np.float32)
        k = np.exp(-0.5 * (x / sigma) ** 2)
        return (k / k.sum()).astype(np.float32)

    kr = _kernel(sigma_rows)
    kc = _kernel(sigma_cols)
    out = np.apply_along_axis(lambda a: np.convolve(a, kr, mode="same"), 0, grid)
    return np.apply_along_axis(lambda a: np.convolve(a, kc, mode="same"), 1, out).astype(np.float32)


def create_heatmap(rows: list[tuple[str, int, float]], title: str) -> io.BytesIO:
    if not AVAILABLE:
        msg = "matplotlib/numpy not available"
        raise ImportError(msg)

    day_index: dict[str, int] = {}
    for day, _, _ in rows:
        day_index.setdefault(day, len(day_index))

    days = list(day_index)
    grid = np.zeros((_SLOTS_PER_DAY, len(days)), dtype=np.float32)
    for day, slot, avg in rows:
        if 0 <= slot < _SLOTS_PER_DAY:
            grid[slot, day_index[day]] = float(avg)

    minutes_per_slot = 24 * 60 / _SLOTS_PER_DAY
    smoothed = _gaussian_blur(grid, sigma_rows=7.5 / minutes_per_slot, sigma_cols=0.5)

    with plt.style.context("dark_background"):
        fig, ax = plt.subplots(figsize=(7, 5), dpi=200)
        img = ax.imshow(
            smoothed,
            aspect="auto",
            origin="lower",
            cmap=_get_cmap(),
            vmin=0,
            vmax=9,
            extent=[0, len(days), 0, _SLOTS_PER_DAY],
        )
        fig.colorbar(img, ax=ax)

        slots_per_hour = 60 // 5
        hour_ticks = list(range(0, _SLOTS_PER_DAY, slots_per_hour))
        ax.set_yticks([t + 0.5 for t in hour_ticks])
        ax.set_yticklabels([f"{h:02d}" for h in range(24)])

        nth = max(1, len(days) // 40)
        day_ticks = list(range(0, len(days), nth))
        ax.set_xticks([t + 0.5 for t in day_ticks])
        ax.set_xticklabels([days[i] for i in day_ticks], rotation=90, ha="center", fontsize=6)

        ax.set_title(title)
        ax.set_ylabel("Hour")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
    buf.seek(0)
    return buf
