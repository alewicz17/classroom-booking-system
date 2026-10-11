from pathlib import Path

import pytest

LAYERS = {"unit", "contract", "integration", "concurrency", "property", "e2e"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # The folder decides the layer, so a test can never be run with the wrong marker.
    for item in items:
        layer = Path(item.fspath).relative_to(Path(__file__).parent).parts[0]
        if layer in LAYERS:
            item.add_marker(layer)
