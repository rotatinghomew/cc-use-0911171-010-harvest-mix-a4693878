import argparse
import json
from pathlib import Path
from records import load, save


def inspect(data, as_of):
    from production import resources
    from demand import offers
    from costing import contribution, check_commitments
    return {"resources": resources(data), "offers": offers(data),
            "single_offer_margin": [contribution(data, row["offer_id"], row["min_kg"]) for row in offers(data)],
            "proposal_check": check_commitments(data, [{"offer_id": "O1", "kg": 50}, {"offer_id": "O2", "kg": 40}])}



def main():
    parser = argparse.ArgumentParser(description="原料分级、意向需求及逐单资源承诺核对。")
    parser.add_argument("action", choices=["demo", "inspect"])
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "fixtures/data.json")
    parser.add_argument("--as-of", default="2026-11-17")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(load(args.data), args.as_of)
    if args.output:
        save(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
