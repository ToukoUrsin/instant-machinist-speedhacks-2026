# Alike sponsor-close handoff

Refreshed at 2026-10-11 16:06 PDT from `integrations/alike/stats.py`, then rendered headlessly with Daytona. This handoff contains the exact files Joel can download from GitHub.

## Files for the lead video thread

The canonical review artifacts are committed beside this file:

- `segment-20s.mp4` — direct 20 s insert
- `overlay-10s-alpha.webm` — transparent overlay
- `overlay-10s.mp4` — green-key fallback
- `segment.html` and `data.js` — source snapshot used for the render

The editable sponsor sources remain in the outer workspace (the sponsor boundary keeps them out of core simulator code):

- `integrations/alike/segment/segment-20s.mp4` — 20 s, 1920x1080 H.264 + AAC
- `integrations/alike/segment/overlay-10s-alpha.webm` — 10 s, 1920x1080 VP9 with alpha
- `integrations/alike/segment/overlay-10s.mp4` — green-key fallback
- `integrations/alike/evidence/stats.md` — refreshed provenance
- `integrations/alike/SEGMENT.md` — shot list and voiceover

## On-screen facts

- Peak Alike-active sessions: **41** at 13:48 PDT (**40 Codex, 1 Claude Code**). This is the Alike event-window metric, not the box-log total.
- Alike analytics: **167 sessions today**, **30 shared decisions**, **127 pointer blocks**, and **116 sessions on the shared simulator task**.
- Local box logs: **153 agents started today** (8 T3 threads + 19 Claude sub-agents + 126 Codex swarm runs; 125 exited 0). Keep this labelled “Box logs · not Alike”.
- The visible coordination moments are the sponsor-folder isolation pointer and the shared simulator acceptance-bar decision.

## Review checks

`ffprobe` verified 20.000 s H.264 1920x1080 output and 10.000 s VP9 1920x1080 output. Frames at 0.5, 1, 5, 6, 8, 10, 12, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, and 19.5 s were inspected. The peak chart now shows the measured 13:45–14:20 PDT window in readable one-minute bars; totals, sponsor-folder isolation, shared decisions, and provenance remain legible.

Use the 20 s segment as a direct final-minute insert, or place the transparent overlay over the lead’s sponsor montage. The source data is in `integrations/alike/segment/data.js`; do not hand-edit numbers without rerunning `python3 sponsors/alike/stats.py` and `python3 sponsors/alike/segment/build_data.py`.
