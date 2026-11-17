import math
import tempfile
import unittest
from pathlib import Path
from records import latest, load, save, fingerprint, quantity


class RecordTests(unittest.TestCase):
    def test_known_time_controls_revision(self):
        rows = [{"id": "A", "recorded_at": "2026-01-01", "value": 1},
                {"id": "A", "recorded_at": "2026-02-01", "value": 2}]
        self.assertEqual(latest(rows, "id", "2026-01-10")[0]["value"], 1)
        self.assertEqual(latest(rows, "id", "2026-02-10")[0]["value"], 2)

    def test_withdrawal_does_not_reveal_older_value(self):
        rows = [{"id": "A", "recorded_at": "2026-01-01"},
                {"id": "A", "recorded_at": "2026-02-01", "withdrawn": True}]
        self.assertEqual(latest(rows, "id", "2026-02-10"), [])

    def test_revision_breaks_same_date_tie(self):
        rows = [{"id": "A", "recorded_at": "2026-01-01", "revision": 2},
                {"id": "A", "recorded_at": "2026-01-01", "revision": 1}]
        self.assertEqual(latest(rows, "id", "2026-01-01")[0]["revision"], 2)

    def test_fingerprint_has_stable_key_order(self):
        self.assertEqual(fingerprint({"group": "东", "kg": 10}), fingerprint({"kg": 10, "group": "东"}))
        self.assertNotEqual(fingerprint({"kg": 10}), fingerprint({"kg": 11}))

    def test_atomic_local_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save(path, {"说明": "本地记录", "kg": 1})
            self.assertEqual(load(path)["kg"], 1)
            save(path, {"kg": 2})
            self.assertEqual(load(path), {"kg": 2})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_nonfinite_and_negative_quantities_rejected(self):
        for value in [-1, math.inf, math.nan]:
            with self.assertRaises(ValueError):
                quantity(value)
