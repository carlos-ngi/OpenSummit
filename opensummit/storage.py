"""Everything the bot needs to remember lives in one json file."""

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path

from .weather import Rules, Spot

log = logging.getLogger(__name__)


class Store:
    def __init__(self, path: Path, default_rules: Rules):
        self.path = path
        self.rules = default_rules
        self.channel_id: int | None = None
        self.spots: list[Spot] = []
        self.last: dict[str, dict] = {}  # spot name -> last weekend status we saw

        if path.exists():
            self._load()
        else:
            self._migrate_old_files()

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Rules)}
        rules = {k: v for k, v in data.get("rules", {}).items() if k in known}
        self.rules = Rules(**{**asdict(self.rules), **rules})
        self.channel_id = data.get("channel_id")
        self.spots = [Spot(**s) for s in data.get("spots", [])]
        self.last = data.get("last", {})

    def _migrate_old_files(self) -> None:
        # older versions (single main.py) kept a locations.json in the folder they ran in
        old = Path("locations.json")
        if not old.exists():
            return
        try:
            for loc in json.loads(old.read_text(encoding="utf-8")).get("locations", []):
                self.spots.append(Spot(str(loc["name"]), float(loc["lat"]), float(loc["lon"])))
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("could not import %s: %s", old, e)
            return
        log.info("imported %d spots from %s", len(self.spots), old.name)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "rules": asdict(self.rules),
            "channel_id": self.channel_id,
            "spots": [asdict(s) for s in self.spots],
            "last": self.last,
        }
        # temp file + replace, so a crash can't leave half a file behind
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def find(self, name: str) -> Spot | None:
        name = name.strip().lower()
        return next((s for s in self.spots if s.name.lower() == name), None)
