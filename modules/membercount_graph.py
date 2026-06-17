from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

AVAILABLE: bool = False

try:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    AVAILABLE = True  # type: ignore[reportConstantRedefinition]
except ImportError:
    pass


def create_member_count_graph(points: list[tuple[datetime, int]], title: str) -> io.BytesIO:
    if not AVAILABLE:
        msg = "matplotlib not available"
        raise ImportError(msg)

    dts, ys = zip(*points, strict=False)
    xs = mdates.date2num(list(dts))  # type: ignore[reportPossiblyUnbound]

    with plt.style.context("dark_background"):  # type: ignore[reportPossiblyUnbound]
        fig, ax = plt.subplots(figsize=(10, 4), dpi=120)
        color = "#5865F2"
        ax.plot(xs, ys, color=color, linewidth=2)
        ax.fill_between(xs, ys, alpha=0.15, color=color)
        ax.xaxis_date()
        ax.margins(x=0, y=0)

        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))  # type: ignore[reportPossiblyUnbound]
        ax.spines[["top", "right"]].set_visible(False)
        # ax.set_ylabel("Members")
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.2)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)

    buf.seek(0)
    return buf
