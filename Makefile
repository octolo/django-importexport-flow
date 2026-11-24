PYTHON ?= python

.PHONY: audit
audit:
	"$(PYTHON)" scripts/audit.py
