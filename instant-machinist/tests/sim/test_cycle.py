import numpy as np
import pytest

from instant_machinist.sim.cycle import (
    FEED_ACCEL_MM_S2,
    _trapezoid_time,
    segment_times,
)
from instant_machinist.sim.gcode import FEED, RAPID, Toolpath


def _tp(p0, p1, kind, feed=6000.0):
    return Toolpath(
        p0=np.asarray([p0], dtype=float), p1=np.asarray([p1], dtype=float),
        kind=np.asarray([kind], dtype=np.int8), tool=np.asarray([1], dtype=np.int32),
        feed=np.asarray([feed], dtype=float), dwell=np.zeros(1),
        nc_line=np.ones(1, dtype=np.int32), program=np.ones(1, dtype=np.int32),
    )


def test_short_block_uses_triangular_acceleration_profile():
    # A 0.1 mm block cannot reach 6000 mm/min at the default acceleration.
    distance = 0.0001
    expected = 2 * np.sqrt(distance / FEED_ACCEL_MM_S2)
    assert _trapezoid_time(distance, 6000.0, FEED_ACCEL_MM_S2) == expected
    assert segment_times(_tp((0, 0, 0), (distance, 0, 0), FEED))[0] == expected


def test_long_block_has_ramp_overhead_but_same_cruise_speed():
    d, f = 1000.0, 6000.0
    constant = d / f * 60.0
    modeled = _trapezoid_time(d, f, FEED_ACCEL_MM_S2)
    assert modeled > constant
    # Relative to an instantaneous-start model, one ``v/a`` of time remains
    # after accounting for the distance covered during both ramps.
    assert modeled - constant == pytest.approx((f / 60.0) / FEED_ACCEL_MM_S2, rel=1e-6)


def test_rapid_keeps_max_axis_distance_and_acceleration_metadata():
    tp = _tp((0, 0, 0), (3, 8, 1), RAPID)
    times = segment_times(tp)
    assert times[0] == _trapezoid_time(8.0, 25000.0, 25000.0)
