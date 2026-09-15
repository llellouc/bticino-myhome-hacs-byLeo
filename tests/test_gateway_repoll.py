"""Tests for gateway re-polling after reconnect."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from homeassistant.components.climate import DOMAIN as CLIMATE
from homeassistant.components.light import DOMAIN as LIGHT

from custom_components.bticino_myhome.const import CONF_PLATFORMS, CONF_WHERE, CONF_ZONE, DOMAIN
from custom_components.bticino_myhome.gateway import MyHOMEGatewayHandler

GATEWAY_MAC = "aa:bb:cc:dd:ee:ff"


@pytest.mark.asyncio
async def test_repoll_uses_device_addresses_not_config_keys() -> None:
    """Re-poll must use configured where/zone values rather than storage keys."""
    sent_messages: list[str] = []

    async def fake_send_status_request(message) -> None:
        sent_messages.append(str(message))

    handler = object.__new__(MyHOMEGatewayHandler)
    handler.hass = SimpleNamespace(
        data={
            DOMAIN: {
                GATEWAY_MAC: {
                    CONF_PLATFORMS: {
                        LIGHT: {
                            "discovered_light_16_chambre": {
                                CONF_WHERE: "16",
                            }
                        },
                        "cover": {
                            "volet_cuisine": {
                                CONF_WHERE: "21",
                            }
                        },
                        CLIMATE: {
                            "climate_nuit": {
                                CONF_ZONE: "#0#4",
                            }
                        },
                    }
                }
            }
        }
    )
    handler.mac = GATEWAY_MAC
    handler.log_id = "test-gateway"
    handler.send_status_request = fake_send_status_request

    await handler._repoll_all_entities()

    assert sent_messages == [
        "*#1*16##",
        "*#2*21##",
        "*#4*#0#4##",
    ]
