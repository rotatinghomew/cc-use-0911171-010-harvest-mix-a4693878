import argparse
import json
from pathlib import Path
from records import load, save


def inspect(data, as_of):
    from production import resources
    from demand import offers
    from costing import contribution, check_commitments
    return {"as_of": as_of, "resources": resources(data), "offers": offers(data),
            "single_offer_margin": [contribution(data, row["offer_id"], row["min_kg"]) for row in offers(data)],
            "proposal_check": check_commitments(data, [{"offer_id": "O1", "kg": 50}, {"offer_id": "O2", "kg": 40}])}


def portfolio_report(data, as_of, include=(), exclude=()):
    """只读的销售组合情景比较：推荐、指定单比较、瓶颈与不变成本。"""
    from portfolio import assets_report
    return {"as_of": as_of, **assets_report(data, include=include, exclude=exclude)}


def main():
    parser = argparse.ArgumentParser(description="原料分级、意向需求、销售组合情景比较及承诺核对。")
    parser.add_argument("action", choices=["demo", "inspect", "portfolio"])
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "fixtures/data.json")
    parser.add_argument("--as-of", default="2026-11-17")
    parser.add_argument("--include", nargs="*", default=[], help="必须加入组合的意向单编号")
    parser.add_argument("--exclude", nargs="*", default=[], help="必须排除的意向单编号")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = load(args.data)
    if args.action == "portfolio":
        result = portfolio_report(data, args.as_of, include=args.include, exclude=args.exclude)
    else:
        result = inspect(data, args.as_of)
    if args.output:
        save(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
