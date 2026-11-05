# Thin wrapper. The real entrypoint is cross-platform: python scripts/homeward.py <cmd>
PY ?= python

setup demo test:
	$(PY) scripts/homeward.py $@

scenario:
	$(PY) scripts/homeward.py scenario $(S)

.PHONY: setup demo test scenario
