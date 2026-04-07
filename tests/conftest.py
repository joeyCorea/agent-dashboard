"""Shared fixtures for all test modules."""

import pytest
import src.parser as parser_module


@pytest.fixture(autouse=True)
def _reset_parser_cache():
    """Reset the module-level session cache between tests."""
    parser_module._cache = None
    yield
    parser_module._cache = None
