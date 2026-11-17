import copy
import json
import unittest
from pathlib import Path

from demand import PriceBook, market_scenarios, quantity_options
from portfolio import (adopt, analysis_basis, bottlenecks, compare, recommend,
                       unchanged_costs)
from production import resource_basis
from records import load


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(load(Path(__file__).parents[1] / "fixtures/data.json"))

    def test_analysis_is_read_only_and_json(self):
        before = copy.deepcopy(self.data)
        report = recommend(self.data)
        self.assertEqual(before, self.data)
        json.dumps(report, ensure_ascii=False, allow_nan=False)
        self.assertEqual(report, recommend(self.data))

    def test_recommendation_is_feasible_in_every_scenario(self):
        report = recommend(self.data)
        self.assertTrue(report["feasible"])
        self.assertTrue(report["robust"])
        self.assertEqual(report["expected"]["weight_covered"], 1.0)
        for scenario in report["scenarios"]:
            self.assertTrue(scenario["admissible"])
            self.assertTrue(scenario["feasible"])
            self.assertEqual(scenario["shortages"], [])

    def test_scenario_prices_move_together(self):
        # 同一情景内 premium 与 bulk 的价格因子按该情景一起应用，不能各取最优。
        scenarios = {row["name"]: row for row in market_scenarios(self.data)}
        weak = PriceBook(self.data, scenarios["weak"]["price_factors"])
        strong = PriceBook(self.data, scenarios["strong"]["price_factors"])
        premium = next(row for row in self.data["offers"] if row["offer_id"] == "O1")
        bulk = next(row for row in self.data["offers"] if row["offer_id"] == "O3")
        self.assertLess(weak.price(premium), strong.price(premium))
        self.assertLess(weak.price(bulk), strong.price(bulk))

    def test_quote_changes_quantity_not_independent(self):
        offer = next(row for row in self.data["offers"] if row["offer_id"] == "O1")
        base = PriceBook(self.data).options(offer)
        weak = PriceBook(self.data, {"premium": 0.85}).options(offer)
        strong = PriceBook(self.data, {"premium": 1.10}).options(offer)
        self.assertLessEqual(max(weak), max(base))
        self.assertLessEqual(max(strong), max(base))
        # 报价与追加量绑定：提价时客户追加量收缩，不能仍按原量交付。
        self.assertNotIn(max(base), strong)
        self.assertLess(max(strong), max(base))

    def test_quantity_options_respect_minimum_and_step(self):
        options = quantity_options(self.data, "O1")
        self.assertTrue(options)
        self.assertGreaterEqual(min(options), 40)
        self.assertTrue(all(abs(value / 10 - round(value / 10)) < 1e-9 for value in options))
        self.assertNotIn(30, options)
        self.assertNotIn(45, options)

    def test_compare_include_and_exclude(self):
        result = compare(self.data, [
            {"name": "base"},
            {"name": "lock O2", "include": ["O2"]},
            {"name": "drop O1", "exclude": ["O1"]},
        ])
        names = [row["name"] for row in result["variants"]]
        self.assertEqual(names, ["base", "lock O2", "drop O1"])
        locked = result["variants"][1]
        self.assertTrue(locked["feasible"])
        self.assertIn("O2", [row["offer_id"] for row in locked["selection"]])
        delta = locked["delta_vs_baseline"]
        self.assertTrue(delta["comparable"])
        self.assertFalse(delta["fixed_cost_changed"])
        self.assertLess(delta["net_cents"], 0)

    def test_infeasible_include_explains_conflict(self):
        report = recommend(self.data, include=["O1", "O2"])
        self.assertFalse(report["feasible"])
        diagnosis = report["diagnosis"]
        self.assertTrue(diagnosis["conflicts"])
        kinds = {row["kind"] for row in diagnosis["conflicts"]}
        self.assertTrue(kinds & {"grade", "capacity"})
        self.assertTrue(all(row.get("reason") for row in diagnosis["conflicts"]))

    def test_excluding_every_offer_is_empty_but_valid(self):
        report = recommend(self.data, exclude=["O1", "O2", "O3"])
        self.assertTrue(report["feasible"])
        self.assertEqual(report["selection"], [])

    def test_bottleneck_names_the_tight_resource(self):
        report = recommend(self.data)
        row = bottlenecks(self.data, report["selection"])
        self.assertTrue(any(entry["resource"] == "A" for entry in row["binding"]))
        self.assertIn("A", row["explanation"])

    def test_unchanged_costs_do_not_depend_on_mix(self):
        left = [{"offer_id": "O1", "kg": 50}, {"offer_id": "O3", "kg": 90}]
        right = [{"offer_id": "O2", "kg": 40}, {"offer_id": "O3", "kg": 90}]
        row = unchanged_costs(self.data, left, right)
        self.assertEqual(row["fixed_cents"], self.data["fixed_cents"])
        self.assertNotEqual(row["variable_cents"]["delta"], 0)
        self.assertEqual(row["unit_variable_cents_per_kg"]["premium"], 100)

    def test_adopt_rechecks_current_basis(self):
        answer = recommend(self.data)
        identity = resource_basis(self.data)
        self.data["offers"][0]["price_cents_per_kg"] = 999
        with self.assertRaises(ValueError):
            adopt(self.data, answer, identity)
        self.assertEqual(self.data["bookings"], [])

    def test_adopt_written_commitment_matches_analysis(self):
        answer = recommend(self.data)
        identity = resource_basis(self.data)
        adopt(self.data, answer, identity)
        from costing import check_commitments
        check = check_commitments(self.data)
        self.assertTrue(check["feasible"])
        accepted = {row["offer_id"] for row in self.data["bookings"]}
        self.assertEqual(accepted, {row["offer_id"] for row in answer["selection"]})

    def test_adopt_rejects_stale_resource_id(self):
        answer = recommend(self.data)
        stale = resource_basis(self.data)
        self.data["capacity_minutes"]["pack"] = 99
        with self.assertRaises(ValueError):
            adopt(self.data, answer, stale)
        self.assertEqual(self.data["bookings"], [])

    def test_adopt_twice_is_rejected(self):
        answer = recommend(self.data)
        identity = resource_basis(self.data)
        adopt(self.data, answer, identity)
        with self.assertRaises(ValueError):
            adopt(self.data, answer, identity)

    def test_existing_bookings_consume_resources_first(self):
        self.data["bookings"] = [{"offer_id": "O1", "kg": 60}]
        report = recommend(self.data)
        self.assertTrue(report["feasible"])
        self.assertNotIn("O1", [row["offer_id"] for row in report["selection"]])
        expected = self.data["raw_lots"][0]["kg"] * 0.6 + self.data["raw_lots"][1]["kg"] * 0.3 - 60 / 0.95
        self.assertAlmostEqual(report["basis"]["remaining_grade_kg"]["A"], expected)


if __name__ == "__main__":
    unittest.main()
