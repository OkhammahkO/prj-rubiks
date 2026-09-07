"""Bridges the ESPHome robot's events/actions to this integration's own services.

Replaces the old `ha_automations/rubiks_robot.yaml` — a manual "copy this file into
your config, and edit it if you renamed the ESPHome device" step. Every one of those
automations just listened for an event and called a service (either one of ours or an
auto-registered `esphome.*` action), so there was nothing in there that actually needed
to live in user-editable YAML. Doing it here means installing via HACS is enough —
no separate file to copy, and a future fix here reaches everyone on update instead of
only people who re-copy the file.

Flow (unchanged from the old YAML — see docs/robot.md for the full sequence):
  HA calls start_scan  ->  robot positions face 1  ->  fires rubiks_face_ready
  -> snapshot + detect -> calls face_scan_done  -> repeat x6
  -> robot fires rubiks_scan_complete -> solve -> execute_solution
  -> robot executes -> fires rubiks_solve_done

  HA robot buttons fire HA events, relayed here to esphome.<device>_<action>:
  rubiks_robot_start_requested -> esphome start_scan
  rubiks_robot_stop_requested  -> esphome stop
  rubiks_robot_advance_face_requested -> esphome face_scan_done
  rubiks_scramble_requested    -> esphome execute_solution (same guards as a real solve)
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceNotFound

from .const import DEFAULT_ESPHOME_DEVICE_NAME, DOMAIN, ESPHOME_DEVICE_NAME

_LOGGER = logging.getLogger(__name__)

# Robot fires the "face ready" / "scan complete" events as soon as the last servo step
# is *dispatched*, not after it physically completes — these settle margins mirror the
# ones the old YAML automations used. See docs/collision-prevention.md "Settle pads".
_FACE_READY_SETTLE_S = 0.3
_SCAN_COMPLETE_SETTLE_S = 1.5


def async_setup_robot_bridge(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register event listeners bridging the ESP32 robot to this integration.

    Unsubscribed automatically on unload via entry.async_on_unload.
    """
    device_name = entry.options.get(
        ESPHOME_DEVICE_NAME,
        entry.data.get(ESPHOME_DEVICE_NAME, DEFAULT_ESPHOME_DEVICE_NAME),
    )
    scan_lock = asyncio.Lock()
    solve_lock = asyncio.Lock()

    async def _esphome_action(action: str, data: dict | None = None) -> None:
        """Call an esphome.<device>_<action> service, raised by ESPHome once connected.

        Not requesting a response — only `execute_solution` supports one
        (`api.respond` in rubiks-solver.yaml), and the original YAML automations never
        actually used the value they captured from it either.
        """
        try:
            await hass.services.async_call(
                "esphome", f"{device_name}_{action}", data or {}, blocking=True
            )
        except ServiceNotFound:
            _LOGGER.error(
                "esphome.%s_%s not found — check the ESPHome device name in this "
                "integration's options matches rubiks-solver.yaml's `esphome: name:`",
                device_name,
                action,
            )

    async def _led_off() -> None:
        # Always the onboard ESP32-S3-CAM flash LED — same device_name prefix as the
        # esphome.* actions above, not the separately-configurable LED Entity ID option
        # (that one's for the illumination light used during scanning, which may not be
        # this same onboard LED).
        await hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": f"light.{device_name}_flash_led"},
            blocking=True,
        )

    async def _on_face_ready(event: Event) -> None:
        if scan_lock.locked():  # mirrors the old automation's mode: single / silent
            return
        async with scan_lock:
            await asyncio.sleep(_FACE_READY_SETTLE_S)
            await hass.services.async_call(
                DOMAIN,
                "robot_scan_face",
                {"face": event.data["face"]},
                blocking=True,
            )
            await _esphome_action("face_scan_done")

    async def _on_scan_complete(_event: Event) -> None:
        if solve_lock.locked():
            return
        async with solve_lock:
            await asyncio.sleep(_SCAN_COMPLETE_SETTLE_S)
            await _led_off()
            result = await hass.services.async_call(
                DOMAIN, "solve", {}, blocking=True, return_response=True
            )
            if not result or "error" in result:
                _LOGGER.warning("Rubiks: solve failed after scan — %s", result)
                return
            await _esphome_action("execute_solution", {"solution": result["solution"]})
            _LOGGER.info(
                "Rubiks: solution sent to robot (%d moves)", result.get("move_count", 0)
            )

    async def _on_solve_done(event: Event) -> None:
        # Safety net — scan-complete already turns the LED off, but a directly-triggered
        # solve (no preceding robot scan) wouldn't have gone through that path.
        await _led_off()
        _LOGGER.info("Rubiks: robot solve complete — %s", event.data)

    async def _on_start_requested(_event: Event) -> None:
        await _esphome_action("start_scan")

    async def _on_stop_requested(_event: Event) -> None:
        await _esphome_action("stop")

    async def _on_advance_face_requested(_event: Event) -> None:
        await _esphome_action("face_scan_done")

    async def _on_scramble_requested(event: Event) -> None:
        await _esphome_action("execute_solution", {"solution": event.data["solution"]})

    listeners = (
        ("esphome.rubiks_face_ready", _on_face_ready),
        ("esphome.rubiks_scan_complete", _on_scan_complete),
        ("esphome.rubiks_solve_done", _on_solve_done),
        (f"{DOMAIN}_robot_start_requested", _on_start_requested),
        (f"{DOMAIN}_robot_stop_requested", _on_stop_requested),
        (f"{DOMAIN}_robot_advance_face_requested", _on_advance_face_requested),
        (f"{DOMAIN}_scramble_requested", _on_scramble_requested),
    )
    for event_type, callback in listeners:
        entry.async_on_unload(hass.bus.async_listen(event_type, callback))
