"""Persistent device state and letter-shard assignment."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DeviceState:
    device_id: str
    shard_index: int
    shard_count: int
    aimd_min: float
    aimd_max: float
    success_streak: int
    consecutive_429: int
    total_requests: int
    total_words_done: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceState":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def _shard_index(device_id: str, shard_count: int) -> int:
    h = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
    return int(h, 16) % max(shard_count, 1)


def load_or_create_state(
    state_path: Path,
    device_id: Optional[str] = None,
    shard_count: int = 1,
) -> DeviceState:
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = DeviceState.from_dict(data)
        if state.shard_count != shard_count:
            state.shard_count = shard_count
            state.shard_index = _shard_index(state.device_id, shard_count)
        return state

    if not device_id:
        device_id = str(uuid.uuid4())
    return DeviceState(
        device_id=device_id,
        shard_index=_shard_index(device_id, shard_count),
        shard_count=shard_count,
        aimd_min=2.0,
        aimd_max=5.0,
        success_streak=0,
        consecutive_429=0,
        total_requests=0,
        total_words_done=0,
    )


def save_state(state: DeviceState, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)


def should_process_letter(state: DeviceState, letter: str) -> bool:
    if state.shard_count <= 1:
        return True
    h = hashlib.sha256(letter.encode("utf-8")).hexdigest()
    return int(h, 16) % state.shard_count == state.shard_index
