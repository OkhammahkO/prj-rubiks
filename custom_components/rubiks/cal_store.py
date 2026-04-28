"""Persistent LAB calibration store for Rubiks Cube Scanner."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .camera_processor import REFERENCE_LAB

_LOGGER = logging.getLogger(__name__)
_STORAGE_VERSION = 1
_EMA_ALPHA = 0.2  # weight given to the new session; 0.8 stays with history


class CalibrationStore:
    """Persists per-camera LAB reference centroids between HA sessions.

    get_references() returns saved anchors merged over the hardcoded defaults —
    saved values always win. Starts with hardcoded REFERENCE_LAB if nothing saved.

    Two update paths:
    - ema_update(): gradual adaptation after every parity-valid calibration
    - hard_commit(): immediate override (manual "Save Calibration" button)
    - reset(): wipe saved anchors, revert to factory defaults
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._saved: dict[str, tuple[float, float, float]] = {}

    @classmethod
    async def create(cls, hass: HomeAssistant, entry_id: str) -> CalibrationStore:
        """Load saved anchors from storage and return a ready instance."""
        store = Store(hass, _STORAGE_VERSION, f"rubiks_cal_{entry_id}")
        obj = cls(store)
        raw = await store.async_load()
        if isinstance(raw, dict):
            try:
                obj._saved = {
                    k: (float(v[0]), float(v[1]), float(v[2]))
                    for k, v in raw.items()
                    if isinstance(v, (list, tuple)) and len(v) == 3
                }
                _LOGGER.info(
                    "Loaded saved LAB anchors for %d colours: %s",
                    len(obj._saved),
                    {c: tuple(round(x, 1) for x in lab) for c, lab in obj._saved.items()},
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Saved LAB anchors could not be parsed — using factory defaults.")
        else:
            _LOGGER.info("No saved LAB anchors — using factory defaults.")
        return obj

    @property
    def has_saved(self) -> bool:
        """True if any custom anchors have been saved."""
        return bool(self._saved)

    def get_references(self) -> dict[str, tuple[float, float, float]]:
        """Return effective LAB reference centroids (saved overrides hardcoded)."""
        refs: dict[str, tuple[float, float, float]] = dict(REFERENCE_LAB)
        refs.update(self._saved)
        return refs

    async def ema_update(
        self, new_anchors: dict[str, tuple[float, float, float]]
    ) -> None:
        """Blend new session anchors into saved using exponential moving average."""
        for colour, new_lab in new_anchors.items():
            if colour in self._saved:
                old = self._saved[colour]
                self._saved[colour] = (
                    (1 - _EMA_ALPHA) * old[0] + _EMA_ALPHA * new_lab[0],
                    (1 - _EMA_ALPHA) * old[1] + _EMA_ALPHA * new_lab[1],
                    (1 - _EMA_ALPHA) * old[2] + _EMA_ALPHA * new_lab[2],
                )
            else:
                self._saved[colour] = new_lab
        _LOGGER.info(
            "EMA calibration update applied (alpha=%.1f). New anchors: %s",
            _EMA_ALPHA,
            {c: tuple(round(x, 1) for x in lab) for c, lab in self._saved.items()},
        )
        await self._persist()

    async def hard_commit(
        self, new_anchors: dict[str, tuple[float, float, float]]
    ) -> None:
        """Replace saved anchors entirely — manual user override."""
        self._saved = dict(new_anchors)
        _LOGGER.info(
            "Calibration hard-committed. Anchors: %s",
            {c: tuple(round(x, 1) for x in lab) for c, lab in self._saved.items()},
        )
        await self._persist()

    async def reset(self) -> None:
        """Clear all saved anchors and revert to hardcoded REFERENCE_LAB."""
        self._saved = {}
        await self._store.async_remove()
        _LOGGER.info("Saved LAB anchors cleared — reverted to factory defaults.")

    async def _persist(self) -> None:
        await self._store.async_save(
            {k: [round(x, 3) for x in lab] for k, lab in self._saved.items()}
        )
