"""Test setup for the API Lambda: put src/ on sys.path and import the real common.audit.

Set LEASH_STUB_COMMON=1 to replace src/common with a stub (emits a loud warning).
"""

import os
import sys
import types
import warnings
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if os.environ.get("LEASH_STUB_COMMON") != "1":
    import common.audit  # noqa: F401  (real Lane B module; ImportError here is a real failure)
else:  # pragma: no cover - explicit opt-in only
    warnings.warn("LEASH_STUB_COMMON=1: src/common is STUBBED, DynamoDB code is not under test")
    common = types.ModuleType("common")
    audit = types.ModuleType("common.audit")
    audit.list_audit = lambda limit=50: []
    common.audit = audit
    sys.modules["common"] = common
    sys.modules["common.audit"] = audit
