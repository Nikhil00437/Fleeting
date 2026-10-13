"""Repo root, for tests that assert against shipped files rather than code.

`tests/` has no package, so this is a module tests import rather than a
relative path: several tests check that a documented file exists and says what
the docs claim, and guessing the depth of `Path(__file__).parents` at each call
site is how one of them ended up reading the wrong directory.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
