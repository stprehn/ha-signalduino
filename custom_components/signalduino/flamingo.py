"""FLAMINGO device handling for SIGNALduino."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FlamingoDevice:
    """Represent a FLAMINGO smoke detector."""

    device_id: str
    protocol: str
    is_alarm: bool = False
    alarm_counter: int = 0

    def receive(self, protocol: str) -> None:
        """Process a received FLAMINGO telegram."""
        self.protocol = protocol

        if not self.is_alarm:
            self.alarm_counter += 1

        self.is_alarm = True
