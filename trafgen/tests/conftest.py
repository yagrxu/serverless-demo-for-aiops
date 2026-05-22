"""Pytest configuration for trafgen tests.

Registers pytest-asyncio in auto mode so async test functions are
automatically recognized without explicit markers.
"""

import pytest_asyncio  # noqa: F401

# pytest-asyncio auto mode is configured in pyproject.toml [tool.pytest.ini_options]
