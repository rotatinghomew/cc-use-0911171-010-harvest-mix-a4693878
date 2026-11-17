import copy
import json
import unittest
from pathlib import Path
from app import inspect
from records import load


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(load(Path(__file__).parents[1] / "fixtures/data.json"))
        self.day = "2026-11-17"

    def test_end_to_end_inspection_is_json_and_repeatable(self):
        before = copy.deepcopy(self.data)
        first = inspect(self.data, self.day)
        self.assertEqual(first, inspect(self.data, self.day))
        self.assertEqual(before, self.data)
        self.assertTrue(json.dumps(first, ensure_ascii=False, allow_nan=False))

    def test_yield_loss_retained(self):
        from production import resources
        row = resources(self.data)
        self.assertLess(sum(row["grade_kg"].values()), row["raw_kg"])

    def test_shared_capacity_detected(self):
        from costing import check_commitments
        combined = check_commitments(self.data, [{"offer_id": "O1", "kg": 50}, {"offer_id": "O2", "kg": 40}])
        self.assertFalse(combined["feasible"])
        self.assertTrue(any(row["kind"] == "capacity" for row in combined["shortages"]))

    def test_fixed_cost_not_in_marginal_contribution(self):
        from costing import contribution
        before = contribution(self.data, "O1", 40)
        self.data["fixed_cents"] *= 2
        self.assertEqual(before, contribution(self.data, "O1", 40))

    def test_minimum_and_package_step(self):
        from demand import validate_quantity
        with self.assertRaises(ValueError):
            validate_quantity(self.data, "O1", 30)
        with self.assertRaises(ValueError):
            validate_quantity(self.data, "O1", 45)

    def test_accept_checks_resource_basis(self):
        from costing import accept
        from production import resources
        identity = resources(self.data)["resource_id"]
        self.data["capacity_minutes"]["pack"] = 99
        with self.assertRaises(ValueError):
            accept(self.data, [{"offer_id": "O1", "kg": 40}], identity)
        self.assertEqual(self.data["bookings"], [])

    def test_feasible_acceptance_is_visible(self):
        from costing import accept, check_commitments
        from production import resources
        accept(self.data, [{"offer_id": "O1", "kg": 40}], resources(self.data)["resource_id"])
        self.assertEqual(len(self.data["bookings"]), 1)
        self.assertTrue(check_commitments(self.data)["feasible"])
