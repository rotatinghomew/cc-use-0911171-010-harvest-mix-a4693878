from demand import validate_quantity
from production import process_usage, resources, compatible
from records import fingerprint


def contribution(data, offer_id, kg):
    offer = validate_quantity(data, offer_id, kg)
    cost = data["products"][offer["product"]]["variable_cents_per_kg"]
    mass = offer["accepted_kg"]
    return {"offer_id": offer_id, "kg": mass, "revenue_cents": round(mass * offer["price_cents_per_kg"]),
            "variable_cents": round(mass * cost), "contribution_cents": round(mass * (offer["price_cents_per_kg"] - cost))}


def check_commitments(data, proposed=()):
    basis = resources(data)
    grades = dict(basis["grade_kg"])
    capacity = dict(basis["capacity_minutes"])
    shortages, allocations = [], []
    seen = set()
    for booking in list(data["bookings"]) + list(proposed):
        if booking["offer_id"] in seen:
            raise ValueError("同一意向单重复承诺")
        seen.add(booking["offer_id"])
        offer = validate_quantity(data, booking["offer_id"], booking["kg"])
        usage = process_usage(data, offer["product"], booking["kg"])
        remaining = usage["input_kg"]
        consumed = {}
        candidates = sorted(grades, key=lambda grade: (grade != usage["input_grade"], grade))
        for grade in candidates:
            if not compatible(data, grade, usage["input_grade"]):
                continue
            taken = min(grades[grade], remaining)
            grades[grade] -= taken
            remaining -= taken
            consumed[grade] = taken
        if remaining > 1e-8:
            shortages.append({"offer_id": booking["offer_id"], "kind": "grade", "resource": usage["input_grade"], "short": remaining})
        for machine, minutes in usage["capacity_minutes"].items():
            capacity[machine] = capacity.get(machine, 0) - minutes
        allocations.append({"offer_id": booking["offer_id"], "consumed_grade_kg": consumed})
    for machine, minutes in capacity.items():
        if minutes < -1e-8:
            shortages.append({"kind": "capacity", "resource": machine, "short": -minutes})
    return {"resource_id": basis["resource_id"], "feasible": not shortages, "shortages": shortages,
            "allocations": allocations, "remaining_grade_kg": grades, "remaining_capacity": capacity}


def accept(data, proposed, expected_resource_id):
    result = check_commitments(data, proposed)
    if result["resource_id"] != expected_resource_id:
        raise ValueError("资源依据已变更")
    if not result["feasible"]:
        raise ValueError("承诺超出可用资源")
    data["bookings"].extend(dict(row) for row in proposed)
    return {"accepted": list(proposed), "receipt_id": fingerprint(data["bookings"])}
