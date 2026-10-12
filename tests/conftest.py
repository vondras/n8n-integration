"""Enable the isolated custom component test environment."""

import pytest


@pytest.fixture(autouse=True)
def custom_components(enable_custom_integrations):
    yield
