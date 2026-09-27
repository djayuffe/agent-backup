# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

"""Shared test setup: import path, and coverage across subprocesses."""
import os
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def pytest_configure(config):
    """Instrument the CLI subprocesses the tests spawn.

    Much of the CLI is exercised by running the scripts through
    ``subprocess``. Those children are only measured when coverage starts
    itself inside them, which it does when ``COVERAGE_PROCESS_START`` names a
    config file. Without this the reported figure is far below the truth.
    """
    if getattr(config.option, "cov_source", None):
        os.environ["COVERAGE_PROCESS_START"] = str(Path(ROOT) / "pyproject.toml")
