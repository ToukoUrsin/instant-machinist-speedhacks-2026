import argparse
import json

import numpy as np

from instant_machinist.render import fake_frames, video


def _args(tmp_path, **kw):
    a = dict(frames=str(tmp_path / "sim/frames.npz"), toolpath=str(tmp_path / "sim/toolpath.npz"), out=str(tmp_path / "x.mp4"),
             fps=30, size="640x360", badge="Verified: 0 gouges", tools=None, max_frames=0, mesh_cells=200, intro=0.5,
             hold=1.0, trail_mm=300.0)
    a.update(kw)
    return argparse.Namespace(**a)


def test_fake_frames_follow_contract(tmp_path):
    fake_frames.main(["--out", str(tmp_path / "sim"), "--frames", "40", "--cell", "0.5"])
    fr = np.load(tmp_path / "sim/frames.npz")
    for k in video.FRAME_KEYS:
        assert k in fr.files
    F, ny, nx = fr["heights"].shape
    assert F == 40 and fr["tool_pos"].shape == (F, 3) and fr["final_gouge"].shape == (ny, nx)
    assert np.all(np.diff(fr["t_sec"]) >= 0)
    # pocket floor reached at the centre, faced top at Z0
    assert abs(np.nanmin(fr["heights"][-1][ny // 2 - 5: ny // 2 + 5, nx // 2]) + 8) < 0.01
    tp = np.load(tmp_path / "sim/toolpath.npz")
    assert set(video.TP_KEYS) <= set(tp.files)


def test_build_data(tmp_path):
    fake_frames.main(["--out", str(tmp_path / "sim"), "--frames", "40", "--cell", "0.5"])
    work = tmp_path / "data"
    work.mkdir()
    n = video.build_data(_args(tmp_path, max_frames=20), work)
    meta = json.loads((work / "meta.json").read_text())
    assert n == 20 + 15 + 30 == len(meta["frames"]["sim"])
    g = meta["grid"]
    assert (work / "heights.bin").stat().st_size == 20 * g["nx"] * g["ny"] * 2
    assert max(g["nx"], g["ny"]) <= 210
    assert meta["tools"]["2"]["label"] == "Ø10 end mill"
    assert [o["label"] for o in meta["ops"]][:2] == ["Facing", "Milling"]
    seg = meta["frames"]["seg"]
    assert seg[0] == 0 and all(b >= a for a, b in zip(seg, seg[1:]))
    assert meta["frames"]["badge"][-1] == 1.0
