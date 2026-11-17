import hashlib
import json
import math
import os
import tempfile
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint(value):
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


def latest(rows, key, known_at):
    selected = {}
    for row in rows:
        if row["recorded_at"] > known_at:
            continue
        identity = row[key]
        current = selected.get(identity)
        if current is None or (row["recorded_at"], row.get("revision", 0)) > (current["recorded_at"], current.get("revision", 0)):
            selected[identity] = dict(row)
    return [selected[identity] for identity in sorted(selected) if not selected[identity].get("withdrawn", False)]


def quantity(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("数量应为有限非负数")
    return number
