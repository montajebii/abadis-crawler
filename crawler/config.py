"""Configuration loading from .env and config/*.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    project_root: Path
    device_id: Optional[str]
    local_db_path: Path
    output_csv: Path
    max_words_per_run: int
    shard_count: int
    debug: bool
    dictionaries_path: Path
    letters_path: Path
    source_mapping_path: Path
    rate_config_path: Path
    schema_path: Path

    @classmethod
    def load(cls, env_file: Optional[Path] = None) -> "Settings":
        if env_file and env_file.exists():
            load_dotenv(env_file)
        else:
            load_dotenv(PROJECT_ROOT / ".env")

        root = PROJECT_ROOT
        return cls(
            project_root=root,
            device_id=os.getenv("DEVICE_ID") or None,
            local_db_path=_resolve(root, os.getenv("LOCAL_DB_PATH", "./local_state.db")),
            output_csv=_resolve(root, os.getenv("OUTPUT_CSV", "./output.csv")),
            max_words_per_run=int(os.getenv("MAX_WORDS_PER_RUN", "200")),
            shard_count=int(os.getenv("SHARD_COUNT", "1")),
            debug=os.getenv("DEBUG", "false").lower() in ("1", "true", "yes"),
            dictionaries_path=root / "config" / "dictionaries.json",
            letters_path=root / "config" / "letters.json",
            source_mapping_path=root / "config" / "source_mapping.json",
            rate_config_path=root / "config" / "rate_config.json",
            schema_path=root / "db" / "schema.sql",
        )

    def load_dictionaries(self) -> list[dict]:
        with open(self.dictionaries_path, "r", encoding="utf-8") as f:
            return json.load(f)["dictionaries"]

    def load_letters(self) -> list[str]:
        with open(self.letters_path, "r", encoding="utf-8") as f:
            return json.load(f)["letters"]

    def load_rate_config(self) -> dict:
        if self.rate_config_path.exists():
            with open(self.rate_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        example = self.project_root / "config" / "rate_config.json.example"
        if example.exists():
            with open(example, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}


def _resolve(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()
