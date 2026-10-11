"""Re-time posted programs under both cycle models: constant feed (used for the published runs) and
trapezoidal acceleration (current simulator default).

    gunzip -k docs/results/ftc-10/best-1001.nc.gz
    .venv/bin/python scripts/retime.py docs/results/ftc-10/best-1001.nc   # or out/<run>/fusion/*/1001.nc
"""
import sys

from instant_machinist.sim.cycle import segment_times
from instant_machinist.sim.gcode import parse_programs


def hms(s: float) -> str:
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}"


for path in sys.argv[1:]:
    r = parse_programs([path])
    tp = r[0] if isinstance(r, tuple) else r
    accel = segment_times(tp).sum()
    const = segment_times(tp, feed_accel_mm_s2=1e12, rapid_accel_mm_s2=1e12).sum()
    print(f"{path}\tconstant-feed {hms(const)}\tacceleration {hms(accel)}")
