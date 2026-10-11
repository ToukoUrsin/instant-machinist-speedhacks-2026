import json
from pathlib import Path

import pytest

from instant_machinist.drawing_cam import run


def spec():
    return {
        "part_number": "CLI-1", "name": "CLI plate", "material": "aluminum",
        "quantity": 1, "units": "mm", "general_tolerance_mm": 0.1,
        "features": [
            {"id": "F1", "type": "face", "z": 0},
            {"id": "F2", "type": "profile", "side": "outside",
             "rect": {"cx": 0, "cy": 0, "w": 40, "h": 30, "r": 3},
             "z_top": 0, "z_bottom": -5},
            {"id": "F3", "type": "pocket", "rect": {"cx": 0, "cy": 0, "w": 20, "h": 12, "r": 4},
             "z_top": 0, "z_bottom": -2},
        ], "notes": [], "questions_for_customer": [],
    }


def test_spec_bridge_exports_cad_cam_and_simulation(tmp_path):
    tools = Path(__file__).parents[1] / "parts" / "sm-101" / "tools.json"
    spec_data = spec()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec_data))
    result = run(None, tmp_path / "job", tools, spec_path)
    assert result["part_number"] == "CLI-1"
    assert Path(result["cad"]["step"]).exists()
    assert Path(result["cad"]["stl"]).exists()
    assert Path(result["program"]).exists()
    assert Path(result["simulation"]).exists()
    assert "cycle_time" in result


def test_missing_input_is_actionable(tmp_path):
    with pytest.raises(ValueError, match="drawing path or --spec"):
        run(None, tmp_path / "job", Path("tools.json"))
