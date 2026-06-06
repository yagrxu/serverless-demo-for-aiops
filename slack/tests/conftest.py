"""Test configuration for the slack integration tests.

Adds lambda source directories to sys.path so test_handler imports resolve.
"""

import sys
from pathlib import Path

# Add all lambda directories to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "lambda" / "webhook-forwarder"))
sys.path.insert(0, str(_root / "lambda" / "slack-handler"))
sys.path.insert(0, str(_root / "lambda" / "slack-worker"))
