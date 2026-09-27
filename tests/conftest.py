# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

"""Make the repository root importable however pytest is invoked."""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
