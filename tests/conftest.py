"""Fixtures for Recorder-backed BTicino integration tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from custom_components.bticino_myhome.const import CONF_ENTITY, DOMAIN

GATEWAY_MAC = "aa:bb:cc:dd:ee:ff"


class HistoryGateway:
    """In-memory F454 history source used by import tests."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.fetch_daily_history = AsyncMock(return_value=rows)
        self.log_id = "test-gateway"


@pytest.fixture
def history_rows() -> list[dict[str, object]]:
    """Return deterministic, completed daily counter rows."""
    today = date.today()
    month = today.month - 2
    year = today.year
    if month <= 0:
        month += 12
        year -= 1

    return [
        {"date": date(year, month, 10), "value": 1500.0},
        {"date": date(year, month, 11), "value": 2500.0},
    ]


@pytest.fixture
def configured_import_view(hass, monkeypatch, history_rows):
    """Create the import view backed by a simulated gateway history."""
    from custom_components.bticino_myhome import web

    gateway_handler = HistoryGateway(history_rows)
    hass.data[DOMAIN] = {GATEWAY_MAC: {CONF_ENTITY: gateway_handler}}

    config = {
        "mac": GATEWAY_MAC,
        "sensor": {
            "test_sensor": {
                "where": "51",
                "name": "Test counter",
                "class": "energy",
                "unit_scale": "base",
            }
        },
    }

    async def get_gateway_config(_hass, gateway):
        assert gateway == GATEWAY_MAC
        return deepcopy(config)

    monkeypatch.setattr(web, "_safe_get_gateway_config", get_gateway_config)
    return web.MyHOMEImportDailyEnergyHistoryView(), gateway_handler, config


def import_request(payload: dict[str, object]) -> SimpleNamespace:
    """Build the minimum authenticated-request shape used by the HA view."""
    return SimpleNamespace(
        app={"hass": None},
        json=AsyncMock(return_value=payload),
    )
