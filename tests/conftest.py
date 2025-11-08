"""Pytest configuration for Glitter tests."""

from __future__ import annotations

import os
from pathlib import Path


def pytest_sessionstart(session):  # type: ignore[override]
    cov_config = Path(__file__).resolve().parent.parent / ".coveragerc"
    if cov_config.exists():
        os.environ.setdefault("COVERAGE_PROCESS_START", str(cov_config))
