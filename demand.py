from records import quantity


def offers(data):
    identities = set()
    result = []
    for row in data["offers"]:
        if row["offer_id"] in identities or row["product"] not in data["products"]:
            raise ValueError("需求编号重复或产品未知")
        identities.add(row["offer_id"])
        minimum, maximum = quantity(row["min_kg"]), quantity(row["max_kg"])
        if minimum > maximum:
            raise ValueError("最低交付量大于需求上限")
        result.append({**row, "min_kg": minimum, "max_kg": maximum})
    return result


def validate_quantity(data, offer_id, kg):
    rows = {row["offer_id"]: row for row in offers(data)}
    if offer_id not in rows:
        raise ValueError("未知意向单")
    row = rows[offer_id]
    mass = quantity(kg)
    if mass and not row["min_kg"] <= mass <= row["max_kg"]:
        raise ValueError("交付量不符合客户条件")
    if abs(mass / row["step_kg"] - round(mass / row["step_kg"])) > 1e-9:
        raise ValueError("交付量不符合整包装单位")
    return {**row, "accepted_kg": mass}


def quoted_volume(data, offer_id, price_cents_per_kg):
    row = next(row for row in offers(data) if row["offer_id"] == offer_id)
    change = (price_cents_per_kg - row["price_cents_per_kg"]) / row["price_cents_per_kg"]
    return max(0, row["max_kg"] * (1 - change * row["price_sensitivity"]))
