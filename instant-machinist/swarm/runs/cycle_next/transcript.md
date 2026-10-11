# Cycle model worker run

- Historical requirements reviewed: `engine/ROADMAP.md` M2 calls for acceleration/jerk and cycle-time estimates within ~5% of Fusion conventions; review checklist requires cycle time on setup sheets and a justified process plan.
- Implemented deterministic rest-to-rest trapezoidal timing for feed and max-axis rapid segments. Short blocks use a triangular profile; longer blocks include acceleration/deceleration ramps.
- Existing report schema remains intact; `cycle_time.total_s`, `total_min`, and per-tool fields remain present.
- Focused tests cover triangular blocks, ramp overhead, and max-axis rapids.
