"""Pytest conftest for langgraph agent tests.

Adds the agent directory to sys.path so that `import server` and
`import streamable_http_sigv4` resolve correctly when pytest runs
from the repository root.
"""
import os
import sys

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
