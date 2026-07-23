"""Tests for F454 daily-history OpenWebNet frames."""

from __future__ import annotations

from datetime import date

from custom_components.bticino_myhome.OWNd.message import OWNEnergyEvent, OWNMessage


def test_f454_daily_history_frame_is_parsed_for_import():
    """Parse the daily-history frame format returned by the F454 on endpoint 51."""
    today = date.today()
    month = today.month - 2
    year = today.year
    if month <= 0:
        month += 12
        year -= 1

    message = OWNMessage.parse(f"*#18*51*513#{month}*10*1500##")

    assert isinstance(message, OWNEnergyEvent)
    assert message.message_type == "daily_consumption"
    assert message.where == "51"
    assert message.daily_consumption == {
        "date": date(year, month, 10),
        "value": 1500,
    }
