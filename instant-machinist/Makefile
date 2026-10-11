# Instant Machinist: common tasks. Python 3.12 venv in .venv (uv).
PY      ?= .venv/bin/python
PART    ?= parts/sm-101
OUT     ?= out
# Native engine runs offline by default (spec from features.json, no video). Drop --no-read to have
# Claude Opus 5.5 read the PDF drawing (needs ANTHROPIC_API_KEY).
NATIVE_FLAGS ?= --no-read --no-video
# Fusion path: reads the drawing (ANTHROPIC_API_KEY), drives cloud Fusion (token ~/.adsk/token.json),
# renders the simulation video (node + playwright chromium + ffmpeg). Add --no-video to skip the render.
FUSION_FLAGS ?=

.PHONY: help install test test-fast demo-native demo-fusion demo-ftc10 verify-example video-native part clean

help:
	@echo "make install        create .venv and install instant-machinist + pytest"
	@echo "make test           run the full test suite"
	@echo "make demo-native    drawing spec -> native CAM engine -> verified G-code   (offline, ~3 s)"
	@echo "make demo-ftc10     NIST FTC-10: STEP + drawing -> Opus 5.5 -> STEP import into cloud Fusion -> verified OP1 programs"
	@echo "make demo-fusion    drawing -> Claude Opus 5.5 -> cloud Fusion -> verified G-code + Fusion file + video"
	@echo "make verify-example re-run the verifier on Fusion's first SM-101 program (finds the gouge at N37935)"
	@echo "make video-native   render the simulation video of the native engine's best program"
	@echo "make part           regenerate parts/sm-101 STEP/STL/drawing from features.json (cadquery)"

install:  # uses uv when available, plain venv + pip otherwise
	@if command -v uv >/dev/null 2>&1; then \
		test -x $(PY) || uv venv .venv --python 3.12; \
		uv pip install --python $(PY) -e ".[dev]"; \
	else \
		test -x $(PY) || python3 -m venv .venv; \
		$(PY) -m pip install -q --upgrade pip && $(PY) -m pip install -q -e ".[dev]"; \
	fi

test:
	$(PY) -m pytest -q tests

test-fast:
	$(PY) -m pytest -q tests/test_smoke.py tests/cam

demo-native:
	$(PY) -m instant_machinist.pipeline --part $(PART) --engine native --out $(OUT)/demo-native $(NATIVE_FLAGS)
	@cat $(OUT)/demo-native/native/native/sim/report.md

demo-fusion:
	$(PY) -m instant_machinist.pipeline --part $(PART) --engine fusion --out $(OUT)/demo-fusion $(FUSION_FLAGS)

demo-ftc10:
	$(PY) -m instant_machinist.pipeline --part parts/ftc-10 --engine fusion --out $(OUT)/demo-ftc10 $(FUSION_FLAGS)

verify-example:
	$(PY) -m instant_machinist.sim.run --part parts/sm-101 --nc docs/examples/sm-101-fusion-first-program.nc \
		--tools docs/examples/fusion-tools.json --out $(OUT)/verify-example --frames 2 || true
	@cat $(OUT)/verify-example/report.md

video-native: demo-native
	$(PY) -m instant_machinist.sim.run --part $(PART) --nc $(OUT)/demo-native/native/native/1001.nc \
		--tools $(PART)/tools.json --out $(OUT)/demo-native/video-sim --frames 360 --quiet
	$(PY) -m instant_machinist.render.video --frames $(OUT)/demo-native/video-sim/frames.npz \
		--toolpath $(OUT)/demo-native/video-sim/toolpath.npz --tools $(PART)/tools.json \
		--out $(OUT)/demo-native/simulation.mp4 --badge "Verified: 0 gouges"

part:
	$(PY) -m instant_machinist.parts.build_part $(PART)

clean:
	rm -rf $(OUT)/demo-native $(OUT)/demo-fusion $(OUT)/demo-ftc10 $(OUT)/verify-example .pytest_cache
