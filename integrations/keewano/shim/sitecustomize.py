"""Loaded only for shop_brain --run subprocesses (PYTHONPATH=shim): limit the native CAM variant search
to the shortlist Shop Brain chose from Keewano history (env IM_SHORTLIST, comma-separated)."""
import os

if os.environ.get("IM_SHORTLIST"):
    try:
        import instant_machinist.cam.optimize as _o
        _all = _o.variants
        _keep = os.environ["IM_SHORTLIST"].split(",")
        _o.variants = lambda: [v for v in _all() if v["name"] in _keep] or _all()
    except Exception:  # core not importable: run unchanged
        pass
