"""Sensor entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COLOUR_EMOJI,
    CUBE_COLORS,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SCAN_LOADING_HINT,
    SCAN_MOTION,
    SCAN_SEQUENCE,
)

_LOGGER = logging.getLogger(__name__)


def _face_grid(colors: list[str]) -> str:
    """Return a 3×3 emoji grid string for a face's 9 colours."""
    rows = [
        "".join(COLOUR_EMOJI.get(colors[row * 3 + col], "⬛") for col in range(3))
        for row in range(3)
    ]
    return "\n".join(rows)


def _cube_net(scanned: dict[str, list[str]]) -> str:
    """Return a cross-shaped emoji net of all 6 faces.

    Layout (15 emojis wide, ⬛ fills empty corners and separates faces):
      ⬛⬛⬛⬛ [W] ⬛⬛⬛⬛⬛⬛⬛⬛
      ⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛  (separator row)
      [O] ⬛ [G] ⬛ [R] ⬛ [B]
      ⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛  (separator row)
      ⬛⬛⬛⬛ [Y] ⬛⬛⬛⬛⬛⬛⬛⬛
    """
    blank = ["?"] * 9

    def face_rows(face: str) -> list[str]:
        colors = scanned.get(face, blank)
        return [
            "".join(COLOUR_EMOJI.get(colors[r * 3 + c], "⬛") for c in range(3))
            for r in range(3)
        ]

    w, o, g, r, y = (
        face_rows("W"), face_rows("O"), face_rows("G"),
        face_rows("R"), face_rows("Y"),
    )
    # B is captured with Yellow at top; the net expects White at top — 180° rotation.
    b = [row[::-1] for row in reversed(face_rows("B"))]

    s = "⬛"
    sep_row = s * 15                          # full-width separator row
    pre = f"{s}{s}{s}{s}"                     # 4 ⬛ before top/bottom face
    suf = f"{s}{s}{s}{s}{s}{s}{s}{s}"        # 8 ⬛ after  top/bottom face

    lines = [
        f"{pre}{w[0]}{suf}",
        f"{pre}{w[1]}{suf}",
        f"{pre}{w[2]}{suf}",
        sep_row,
        f"{o[0]}{s}{g[0]}{s}{r[0]}{s}{b[0]}",
        f"{o[1]}{s}{g[1]}{s}{r[1]}{s}{b[1]}",
        f"{o[2]}{s}{g[2]}{s}{r[2]}{s}{b[2]}",
        sep_row,
        f"{pre}{y[0]}{suf}",
        f"{pre}{y[1]}{suf}",
        f"{pre}{y[2]}{suf}",
    ]
    return "\n" + "\n".join(lines)

CUBE_STATE_SENSOR = SensorEntityDescription(
    key="cube_state", translation_key="cube_state"
)
CURRENT_FACE_SENSOR = SensorEntityDescription(
    key="current_face", translation_key="current_face"
)
FACES_SCANNED_SENSOR = SensorEntityDescription(
    key="faces_scanned", translation_key="faces_scanned"
)
SCAN_WARNINGS_SENSOR = SensorEntityDescription(
    key="scan_warnings", translation_key="scan_warnings"
)
KOCIEMBA_INPUT_SENSOR = SensorEntityDescription(
    key="kociemba_input", translation_key="kociemba_input"
)
SOLUTION_SENSOR = SensorEntityDescription(
    key="solution", translation_key="solution"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks sensor entities."""
    async_add_entities([
        CubeStateSensor(hass, entry),
        CurrentFaceSensor(hass, entry),
        FacesScannedSensor(hass, entry),
        ScanWarningSensor(hass, entry),
        KociembaInputSensor(hass, entry),
        SolutionSensor(hass, entry),
    ])


class RubiksSensorBase(SensorEntity):
    """Base sensor with shared device info and event subscription."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to scan events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_face_scanned)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_rejected", self._on_image_update)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_calibrated", self._on_calibrated)
        )

    @callback
    def _on_calibrated(self, event: Event) -> None:
        """Handle calibration completion — subclasses override as needed."""

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        """Handle a face scanned event."""

    @callback
    def _on_reset(self, event: Event) -> None:
        """Handle a scan reset event."""

    @callback
    def _on_image_update(self, event: Event) -> None:
        """Handle a preview/rejected event (image loaded but not stored)."""

    def _scanned(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]


class CubeStateSensor(RubiksSensorBase):
    """Full cube state once all 6 faces are scanned (54-char string)."""

    entity_description = CUBE_STATE_SENSOR
    _attr_native_value: str | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_cube_state"
        self._attr_extra_state_attributes: dict[str, Any] = self._base_attrs()

    async def async_added_to_hass(self) -> None:
        """Subscribe to scan, calibration, and cal-store events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_calibration_saved", self._on_cal_store_changed)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_calibration_reset", self._on_cal_store_changed)
        )

    def _base_attrs(self) -> dict[str, Any]:
        return {
            "faces scanned": "0 of 6",
            "faces still needed": " → ".join(SCAN_SEQUENCE),
            "colour references": self._cal_source(),
        }

    def _cal_source(self) -> str:
        cal_store = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("cal_store")
        if cal_store and cal_store.has_saved:
            return "saved (adapted to your camera)"
        return "factory defaults"

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        scanned = self._scanned()
        missing = [c for c in SCAN_SEQUENCE if c not in scanned]
        n = len(scanned)
        self._attr_native_value = (
            "".join("".join(scanned[c]) for c in SCAN_SEQUENCE if c in scanned)
            if n == 6 else None
        )
        warnings = event.data.get("warnings") or []
        self._attr_extra_state_attributes = {
            **self._attr_extra_state_attributes,
            "faces scanned": f"{n} of 6",
            "faces still needed": " → ".join(missing) if missing else "none",
            "scan warnings": "; ".join(warnings) if warnings else "none",
        }
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = None
        self._attr_extra_state_attributes = {**self._base_attrs(), "scan warnings": "none"}
        self.async_write_ha_state()

    @callback
    def _on_calibrated(self, event: Event) -> None:
        scanned = self._scanned()
        if len(scanned) != 6:
            return
        self._attr_native_value = "".join(
            "".join(scanned[c]) for c in SCAN_SEQUENCE if c in scanned
        )
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        result = data.get("calibration_result")
        warnings = data.get("scan_warnings") or []
        attrs: dict[str, Any] = {
            "faces scanned": "6 of 6",
            "faces still needed": "none",
            "colour references": self._cal_source(),
            "scan warnings": "; ".join(warnings) if warnings else "none",
        }
        if result:
            attrs["cube is valid"] = result.parity_valid
            if result.parity_error:
                attrs["validation error"] = result.parity_error
            elif "validation error" in self._attr_extra_state_attributes:
                attrs["validation error"] = None
            attrs["corrections applied"] = (
                f"{len(result.pre_calibration_changes)} squares reassigned"
                if result.pre_calibration_changes
                else "none"
            )
            attrs["uncertain stickers"] = (
                f"{len(result.low_confidence)} stickers below confidence threshold"
                if result.low_confidence
                else "none"
            )
        attrs["cube"] = _cube_net(scanned)
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()

    @callback
    def _on_cal_store_changed(self, event: Event) -> None:
        self._attr_extra_state_attributes = {
            **self._attr_extra_state_attributes,
            "colour references": self._cal_source(),
        }
        self.async_write_ha_state()


def _face_status(face: str, done: int) -> str:
    """Format the CurrentFaceSensor state string."""
    return f"{CUBE_COLORS[face].capitalize()} · {SCAN_MOTION[face]} ({done} of 6 done)"


class CurrentFaceSensor(RubiksSensorBase):
    """Shows the next face to scan with the required motion."""

    entity_description = CURRENT_FACE_SENSOR

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_face"
        self._attr_native_value: str = _face_status(SCAN_SEQUENCE[0], 0)
        self._attr_extra_state_attributes: dict[str, Any] = {
            "next_colour": CUBE_COLORS[SCAN_SEQUENCE[0]].capitalize(),
            "motion": SCAN_MOTION[SCAN_SEQUENCE[0]],
            "loading_position": SCAN_LOADING_HINT,
            "remaining": " → ".join(CUBE_COLORS[c].capitalize() for c in SCAN_SEQUENCE),
        }

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        scanned = self._scanned()
        done = len(scanned)
        if done >= 6:
            self._attr_native_value = "complete"
            self._attr_extra_state_attributes = {"remaining": "none"}
        else:
            next_face = SCAN_SEQUENCE[done]
            self._attr_native_value = _face_status(next_face, done)
            attrs: dict[str, Any] = {
                "next_colour": CUBE_COLORS[next_face].capitalize(),
                "motion": SCAN_MOTION[next_face],
                "remaining": " → ".join(
                    CUBE_COLORS[c].capitalize()
                    for c in SCAN_SEQUENCE if c not in scanned
                ),
            }
            if next_face == "W":
                attrs["loading_position"] = SCAN_LOADING_HINT
            self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        first = SCAN_SEQUENCE[0]
        self._attr_native_value = _face_status(first, 0)
        self._attr_extra_state_attributes = {
            "next_colour": CUBE_COLORS[first].capitalize(),
            "motion": SCAN_MOTION[first],
            "loading_position": SCAN_LOADING_HINT,
            "remaining": " → ".join(CUBE_COLORS[c].capitalize() for c in SCAN_SEQUENCE),
        }
        self.async_write_ha_state()


class FacesScannedSensor(RubiksSensorBase):
    """Count of scanned faces (0-6) with per-face colour data as attributes."""

    entity_description = FACES_SCANNED_SENSOR
    _attr_native_value: int = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_faces_scanned"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        scanned = self._scanned()
        self._attr_native_value = len(scanned)
        self._attr_extra_state_attributes = {
            **self._face_detail_attrs(),
            **self._image_context(),
        }
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = 0
        self._attr_extra_state_attributes = self._image_context()
        self.async_write_ha_state()

    def _face_detail_attrs(self) -> dict:
        """Return per-face square detail and emoji grid keyed by face label."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        face_scans = data.get("face_scans", {})
        scanned = self._scanned()
        attrs: dict = {}
        for face_label, colors in scanned.items():
            scan = face_scans.get(face_label)
            if scan and len(scan.lab_readings) == 9:
                attrs[face_label] = [
                    {"color": c, "L": round(L, 1), "a": round(a, 1), "b": round(b, 1)}
                    for c, (L, a, b) in zip(colors, scan.lab_readings)
                ]
            else:
                attrs[face_label] = colors
            attrs[f"{face_label} grid"] = _face_grid(colors)
        return attrs

    @callback
    def _on_image_update(self, event: Event) -> None:
        """Update image size attributes after a preview."""
        self._attr_extra_state_attributes = {
            **{k: v for k, v in self._attr_extra_state_attributes.items()
               if k not in ("image_width", "image_height")},
            **self._image_context(),
        }
        self.async_write_ha_state()

    @callback
    def _on_calibrated(self, event: Event) -> None:
        """Expose calibration result as attributes."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        result = data.get("calibration_result")
        if result is None:
            return
        self._attr_extra_state_attributes = {
            **self._face_detail_attrs(),
            "parity_valid": result.parity_valid,
            "parity_error": result.parity_error,
            "calibration_anchors": result.anchors,
            "low_confidence_stickers": result.low_confidence,
            "pre_calibration_changes": result.pre_calibration_changes,
        }
        self.async_write_ha_state()

    def _image_context(self) -> dict:
        """Return image dimensions for display context."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        size = data.get("image_size")
        if size:
            return {"image_width": size[0], "image_height": size[1]}
        return {}


class ScanWarningSensor(RubiksSensorBase):
    """Count of active scan warnings — 0 means all clear."""

    entity_description = SCAN_WARNINGS_SENSOR
    _attr_native_value: int = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_scan_warnings"
        self._attr_extra_state_attributes: dict[str, Any] = {"warnings": []}

    def _apply_warnings(self, warnings: list[str]) -> None:
        self._attr_native_value = len(warnings)
        self._attr_extra_state_attributes = {
            "status": "🟢 All clear" if not warnings else f"🔴 {len(warnings)} warning{'s' if len(warnings) != 1 else ''}",
            "warnings": warnings if warnings else [],
        }
        self.async_write_ha_state()

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        self._apply_warnings(event.data.get("warnings") or [])

    @callback
    def _on_calibrated(self, event: Event) -> None:
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        result = data.get("calibration_result")
        warnings: list[str] = list(data.get("scan_warnings") or [])
        if result:
            if result.parity_error:
                warnings.append(f"Cube is not valid: {result.parity_error}")
            if result.low_confidence:
                n = len(result.low_confidence)
                warnings.append(
                    f"{n} sticker{'s' if n != 1 else ''} below confidence threshold"
                )
        self._apply_warnings(warnings)

    @callback
    def _on_reset(self, event: Event) -> None:
        self._apply_warnings([])


class KociembaInputSensor(RubiksSensorBase):
    """54-character kociemba input string — the exact value passed to kociemba.solve()."""

    entity_description = KOCIEMBA_INPUT_SENSOR
    _attr_native_value: str | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_kociemba_input"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @callback
    def _on_calibrated(self, event: Event) -> None:
        cube_str = event.data.get("kociemba_string")
        self._attr_native_value = cube_str
        self._attr_extra_state_attributes = {
            "parity_valid": event.data.get("parity_valid"),
            "ready_to_solve": cube_str is not None,
        }
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()


class SolutionSensor(RubiksSensorBase):
    """Move sequence produced by the kociemba solver."""

    entity_description = SOLUTION_SENSOR
    _attr_native_value: str | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_solution"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to solve and reset events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_solved", self._on_solved)
        )

    @callback
    def _on_solved(self, event: Event) -> None:
        solution: str = event.data.get("solution", "")
        self._attr_native_value = solution
        self._attr_extra_state_attributes = {
            "move_count": event.data.get("move_count", 0),
            "cube_string": event.data.get("cube_string"),
        }
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()

    @callback
    def _on_calibrated(self, event: Event) -> None:
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()
