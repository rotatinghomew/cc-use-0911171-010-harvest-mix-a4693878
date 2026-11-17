"""逐单贡献、整组资源核对与分析/承诺共用的收益口径。

``contribution``（逐单账面）与 ``evaluate``（组合口径）使用同一套收入与变动
成本计算。固定成本不随组合改变，既不进入逐单贡献，也不因换方案而消失，只在
组合对比中单独列示。
"""
from demand import PriceBook, offer_row, validate_quantity
from production import allocate, resource_basis, substitute_grades

EPS = 1e-8


def _variable_cents(data, product, kg):
    return kg * data["products"][product]["variable_cents_per_kg"]


def contribution(data, offer_id, kg):
    offer = validate_quantity(data, offer_id, kg)
    mass = offer["accepted_kg"]
    revenue = mass * offer["price_cents_per_kg"]
    variable = _variable_cents(data, offer["product"], mass)
    return {"offer_id": offer_id, "kg": mass, "revenue_cents": round(revenue),
            "variable_cents": round(variable), "contribution_cents": round(revenue - variable)}


def check_commitments(data, proposed=()):
    # 已写入的承诺由 allocate 统一先占用资源，这里只补入待承诺的单。
    for booking in proposed:
        validate_quantity(data, booking["offer_id"], booking["kg"])
    basis = allocate(data, proposed)
    return {"resource_id": resource_basis(data), "feasible": basis["feasible"],
            "shortages": basis["shortages"], "allocations": basis["allocations"],
            "remaining_grade_kg": basis["remaining_grade_kg"],
            "remaining_capacity": basis["remaining_capacity"],
            "usage_grade_kg": basis["usage_grade_kg"], "usage_capacity": basis["usage_capacity"]}


def explain_conflicts(data, shortages):
    """把短缺口径翻译成业务冲突：争夺的等级、可降级来源、受限机时。"""
    supply = {grade for row in data["raw_lots"] for grade in row["yield_fraction"]}
    conflicts = []
    for row in shortages:
        if row["kind"] == "grade":
            alternatives = substitute_grades(data, row["resource"], supply)
            if alternatives:
                reason = (f"{row['resource']} 级原料不足，可降级来源"
                          f"{'、'.join(alternatives)} 也已用尽")
            else:
                reason = f"{row['resource']} 级原料不足，且没有可降级来源"
            conflicts.append({"kind": "grade", "resource": row["resource"], "short": row["short"],
                              "offer_id": row.get("offer_id"),
                              "alternative_grades": alternatives, "reason": reason})
        else:
            conflicts.append({"kind": "capacity", "resource": row["resource"], "short": row["short"],
                              "offer_id": row.get("offer_id"),
                              "reason": f"{row['resource']} 环节机时不足"})
    return conflicts


def evaluate(data, selection, book=None):
    """评估一组（意向单，交付量）选择，不修改输入。

    返回收益、变动成本、固定成本、净额、闲置原料/机时、短缺与冲突。分析得到的
    ``allocations`` 与实际承诺校验使用同一分配算法。
    """
    if book is None:
        book = PriceBook(data)
    rows, revenue, variable = [], 0.0, 0.0
    for item in selection:
        offer = offer_row(data, item["offer_id"])
        kg = validate_quantity(data, item["offer_id"], item["kg"])["accepted_kg"]
        if kg <= 0:
            continue
        price = book.price(offer)
        revenue += kg * price
        variable += _variable_cents(data, offer["product"], kg)
        rows.append({"offer_id": item["offer_id"], "product": offer["product"], "kg": kg,
                     "price_cents_per_kg": round(price, 6), "revenue_cents": round(kg * price, 6)})
    basis = allocate(data, rows)
    contribution = revenue - variable
    fixed = data.get("fixed_cents", 0)
    return {
        "selection": rows,
        "feasible": basis["feasible"],
        "revenue_cents": round(revenue, 6),
        "variable_cents": round(variable, 6),
        "contribution_cents": round(contribution, 6),
        "fixed_cents": fixed,
        "net_cents": round(contribution - fixed, 6),
        "usage_grade_kg": {grade: round(mass, 6) for grade, mass in basis["usage_grade_kg"].items()},
        "idle_grade_kg": {grade: round(mass, 6) for grade, mass in basis["remaining_grade_kg"].items()},
        "usage_capacity": {machine: round(minutes, 6) for machine, minutes in basis["usage_capacity"].items()},
        "idle_capacity": {machine: round(minutes, 6) for machine, minutes in basis["remaining_capacity"].items()},
        "shortages": basis["shortages"],
        "conflicts": explain_conflicts(data, basis["shortages"]),
        "allocations": basis["allocations"],
    }


def accept(data, proposed, expected_resource_id):
    """采纳方案前按当前基础数据重新核对；依据过期或不可行都不写入。"""
    current = resource_basis(data)
    if current != expected_resource_id:
        raise ValueError("资源依据已变更")
    result = check_commitments(data, proposed)
    if not result["feasible"]:
        raise ValueError("承诺超出可用资源")
    data["bookings"].extend(dict(row) for row in proposed)
    data.setdefault("acceptances", []).append(
        {"resource_id": current, "selection": [dict(row) for row in proposed]})
    return {"accepted": list(proposed), "receipt_id": current}
