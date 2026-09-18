"""Test setup for Lane B: real src/common on sys.path, local Cedar evaluation, no AWS."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AUDIT_TABLE", "leash-audit-test")


@pytest.fixture
def local_authz(monkeypatch):
    """Evaluate with cedarpy against cedar/ instead of Verified Permissions."""
    monkeypatch.setenv("LEASH_LOCAL_AUTHZ", "1")
    monkeypatch.delenv("LEASH_CEDAR_DIR", raising=False)
