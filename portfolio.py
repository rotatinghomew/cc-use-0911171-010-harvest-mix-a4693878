"""销售组合的情景比较。

在不改动真实接单记录的前提下，用当前原料、分级损耗、降级范围和产线能力评估
一组可执行的意向单选择：

- ``recommend``：在全部市场情景下都可执行的推荐组合。
- ``compare``：业务员加入/排除指定单后的并排比较（收益、闲置、短缺）。
- ``bottlenecks``：真正制约收益的资源及受限原因。
- ``unchanged_costs``：换方案也不会改变的成本。
- ``adopt``：采纳方案前按当前基础数据重新核对。

价格与数量不是独立条件：同一市场情景内所有产品价格一起变动，报价同时决定客户
愿意接受的追加量。每个方案都在同一情景内用同一组价格因子评估，绝不把各产品最
乐观的条件拼成一个不存在的组合。方案必须在该情景下可交付，才计入期望收益。
"""
from records import fingerprint
from demand import PriceBook, demand_basis, market_scenarios, offer_row, quantity_options, quoted_volume
from production import allocate, compatible, process_usage, resource_basis, resources, substitute_grades
from costing import accept as accept_commitments, evaluate

EPS = 1e-8
DEFAULT_LIMIT = 200000


def _book(data, scenario):
    return PriceBook(data, scenario["price_factors"])


def analysis_basis(data):
    """一次分析的完整依据：原料/能力、需求/价格与固定成本。

    任何一项变化都会让旧建议失效，采纳时必须重新分析，而不是沿用过期结论。
    """
    return fingerprint({"resource": resource_basis(data), "demand": demand_basis(data),
                        "fixed_cents": data.get("fixed_cents", 0)})


def _remaining_basis(data):
    """已有承诺先占用原料和机时，组合分析只用剩余部分。"""
    current = allocate(data, [])
    if not current["feasible"]:
        raise ValueError("已有承诺已超出可用资源，无法在剩余能力上比较组合")
    return current["remaining_grade_kg"], current["remaining_capacity"]


def _compatible_supply(data, grades):
    requested = set(grades)
    for row in data["products"].values():
        requested.add(row["input_grade"])
    return {grade: sum(mass for source, mass in grades.items() if compatible(data, source, grade))
            for grade in requested}


def _plan_selection(plan):
    return [{"offer_id": offer_id, "kg": mass} for offer_id, mass in sorted(plan.items()) if mass > 0]


def _enumerate_plans(data, include=(), exclude=(), grades=None, capacity=None, limit=DEFAULT_LIMIT):
    """枚举整包装交付量组合，并用资源必要条件剪枝。

    剪枝只使用“任何可行分配都必须满足”的条件（机时总量、各等级及其可降级来源的
    总量），不会误删可行组合；最终可行性仍由 ``allocate`` 判定。
    """
    include, exclude = list(include), list(exclude)
    for offer_id in include + exclude:
        offer_row(data, offer_id)
    if set(include) & set(exclude):
        raise ValueError("同一意向单不能同时加入和排除")
    if grades is None or capacity is None:
        grades, capacity = _remaining_basis(data)
    limits = _compatible_supply(data, grades)

    offers = [row for row in sorted((offer_row(data, offer["offer_id"]) for offer in data["offers"]),
                                    key=lambda row: row["offer_id"])
              if row["offer_id"] not in exclude]
    sizes = []
    for offer in offers:
        options = quantity_options(data, offer["offer_id"])
        if offer["offer_id"] in include:
            if not options:
                return []
            sizes.append(options)
        else:
            sizes.append([0.0] + options)

    plans = []

    def walk(index, plan, minutes, required):
        if index == len(offers):
            plans.append(dict(plan))
            if len(plans) > limit:
                raise ValueError("组合空间过大，请用加入/排除缩小范围")
            return
        offer = offers[index]
        usage = process_usage(data, offer["product"], 1.0)
        for mass in sizes[index]:
            step_minutes = {machine: value * mass for machine, value in usage["capacity_minutes"].items()}
            if any(minutes.get(machine, 0.0) + value > capacity.get(machine, 0.0) + EPS
                   for machine, value in step_minutes.items()):
                continue
            needed = usage["input_kg"] * mass
            total_required = required.get(usage["input_grade"], 0.0) + needed
            if total_required > limits.get(usage["input_grade"], 0.0) + EPS:
                continue
            plan[offer["offer_id"]] = mass
            for machine, value in step_minutes.items():
                minutes[machine] = minutes.get(machine, 0.0) + value
            previous = required.get(usage["input_grade"], 0.0)
            required[usage["input_grade"]] = total_required
            walk(index + 1, plan, minutes, required)
            required[usage["input_grade"]] = previous
            for machine, value in step_minutes.items():
                minutes[machine] -= value
            plan.pop(offer["offer_id"], None)

    walk(0, {}, {}, {})
    return plans


def _assess(data, plan, book):
    selection = _plan_selection(plan)
    quotes = []
    for item in selection:
        offer = offer_row(data, item["offer_id"])
        options = book.options(offer)
        if not any(abs(item["kg"] - option) <= EPS for option in options):
            quotes.append({"offer_id": item["offer_id"], "kg": item["kg"],
                           "quoted_max_kg": round(quoted_volume(data, item["offer_id"], book.price(offer)), 6),
                           "reason": "交付量超过该情景报价下客户的追加量上限"})
    result = evaluate(data, selection, book)
    return {"selection": selection, "result": result,
            "admissible": not quotes and result["feasible"],
            "quote_conflicts": quotes}


def _expected(entries):
    """entries: [(weight, result)]；情景内结果只有可交付时才会传入。"""
    contribution = sum(weight * result["contribution_cents"] for weight, result in entries)
    net = sum(weight * result["net_cents"] for weight, result in entries)
    return {"contribution_cents": round(contribution, 6), "net_cents": round(net, 6),
            "weight_covered": round(sum(weight for weight, _ in entries), 9)}


def _scenario_summary(name, weight, assessment):
    result = assessment["result"]
    return {"scenario": name, "weight": weight, "admissible": assessment["admissible"],
            "quote_conflicts": assessment["quote_conflicts"],
            "feasible": result["feasible"], "shortages": result["shortages"],
            "conflicts": result["conflicts"],
            "contribution_cents": result["contribution_cents"], "net_cents": result["net_cents"],
            "idle_capacity": result["idle_capacity"], "idle_grade_kg": result["idle_grade_kg"]}


def _solve(data, scenarios, include=(), exclude=(), limit=DEFAULT_LIMIT):
    """找一个方案：在所有情景可交付且资源可行，按情景权重最大化期望净收益。"""
    books = {scenario["name"]: _book(data, scenario) for scenario in scenarios}
    remaining = _remaining_basis(data)
    plans = _enumerate_plans(data, include=include, exclude=exclude,
                             grades=remaining[0], capacity=remaining[1], limit=limit)
    best_all, best_any = None, None
    for plan in plans:
        assessments = {name: _assess(data, plan, book) for name, book in books.items()}
        covered = [(scenario["weight"], assessments[scenario["name"]]["result"])
                   for scenario in scenarios if assessments[scenario["name"]]["admissible"]]
        score = sum(weight * result["net_cents"] for weight, result in covered)
        candidate = {"plan": plan, "assessments": assessments, "score": score}
        if len(covered) == len(scenarios):
            if best_all is None or score > best_all["score"] + EPS:
                best_all = candidate
        if best_any is None or score > best_any["score"] + EPS:
            best_any = candidate
    return best_all, best_any


def _diagnose(data, scenarios, best_any, include=(), exclude=()):
    """没有可交付方案时，说明相互冲突的资源或交付条件。"""
    if best_any is None:
        forced = [offer_row(data, offer_id) for offer_id in include]
        combos = _forced_plans(data, forced)
        if not combos:
            return {"reason": "指定意向单没有可执行的交付量", "conflicts": [], "quote_conflicts": []}
        conflicts, quotes, shortages = [], [], []
        for plan in combos:
            assessment = _assess(data, plan, _book(data, scenarios[0]))
            conflicts.extend(assessment["result"]["conflicts"])
            quotes.extend(assessment["quote_conflicts"])
            shortages.extend(assessment["result"]["shortages"])
        reason = ("指定意向单与已有承诺及其他指定单无法同时交付（已有承诺已先占用原料和机时）"
                  if data.get("bookings") else "指定意向单之间无法同时交付")
        return {"reason": reason,
                "selection": _plan_selection(combos[0]),
                "forced_alternatives": [_plan_selection(plan) for plan in combos],
                "conflicts": _unique(conflicts, ("kind", "resource", "reason")),
                "shortages": _unique(shortages, ("offer_id", "kind", "resource")),
                "quote_conflicts": _unique(quotes, ("offer_id", "reason"))}
    conflicts, quotes, missing = [], [], []
    for scenario in scenarios:
        assessment = best_any["assessments"][scenario["name"]]
        if assessment["admissible"]:
            continue
        missing.append(scenario["name"])
        for row in assessment["quote_conflicts"]:
            quotes.append({"scenario": scenario["name"], **row})
        for row in assessment["result"]["conflicts"]:
            conflicts.append({"scenario": scenario["name"], **row})
    return {"reason": "该组意向单不能在全部市场情景下同时交付",
            "selection": _plan_selection(best_any["plan"]),
            "missing_scenarios": missing,
            "conflicts": _unique(conflicts, ("kind", "resource", "reason")),
            "quote_conflicts": _unique(quotes, ("offer_id", "reason"))}


def _forced_plans(data, forced, limit=2000):
    """只含指定单的交付量组合，用于解释这些单之间的冲突。"""
    if not forced:
        return []
    sizes = [quantity_options(data, offer["offer_id"]) for offer in forced]
    if any(not options for options in sizes):
        return []
    plans, current = [], []

    def walk(index):
        if len(plans) >= limit:
            return
        if index == len(forced):
            plans.append({offer["offer_id"]: mass for offer, mass in zip(forced, current)})
            return
        for mass in sizes[index]:
            current.append(mass)
            walk(index + 1)
            current.pop()

    walk(0)
    return plans


def _unique(rows, keys):
    seen, result = set(), []
    for row in rows:
        identity = tuple(row.get(key) for key in keys)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(row)
    return result


def recommend(data, include=(), exclude=(), limit=DEFAULT_LIMIT):
    """推荐组合：全部情景可交付、资源可行，按情景权重取期望净收益最高者。"""
    scenarios = market_scenarios(data)
    best_all, best_any = _solve(data, scenarios, include=include, exclude=exclude, limit=limit)
    basis = resource_basis(data)
    if best_all is None:
        return {"resource_id": basis, "analysis_id": analysis_basis(data), "feasible": False,
                "selection": [], "diagnosis": _diagnose(data, scenarios, best_any, include, exclude),
                "note": "没有方案能在全部市场情景下交付；不会用局部最优拼成推荐。"}
    scenario_rows = [_scenario_summary(scenario["name"], scenario["weight"],
                                       best_all["assessments"][scenario["name"]])
                     for scenario in scenarios]
    entries = [(scenario["weight"], best_all["assessments"][scenario["name"]]["result"])
               for scenario in scenarios]
    remaining_grades, remaining_capacity = _remaining_basis(data)
    return {"resource_id": basis, "analysis_id": analysis_basis(data), "feasible": True, "robust": True,
            "selection": _plan_selection(best_all["plan"]),
            "not_taken": sorted(offer["offer_id"] for offer in data["offers"]
                                if offer["offer_id"] not in best_all["plan"]
                                or best_all["plan"][offer["offer_id"]] <= 0),
            "expected": _expected(entries), "scenarios": scenario_rows,
            "basis": {"grade_kg": resources(data)["grade_kg"],
                      "capacity_minutes": resources(data)["capacity_minutes"],
                      "remaining_grade_kg": remaining_grades,
                      "remaining_capacity": remaining_capacity},
            "note": "推荐组合在全部市场情景下均可交付；没有跨情景拼接价格或数量。"}


def compare(data, variants, limit=DEFAULT_LIMIT):
    """并排比较若干方案。

    ``variants`` 为 ``{"name", "include", "exclude"}``。第一个方案作为基准；每个
    方案都按同一批市场情景与情景权重评估，差异同时列出收益、闲置和短缺。
    """
    if not variants:
        raise ValueError("至少需要一个比较方案")
    scenarios = market_scenarios(data)
    solved = []
    for variant in variants:
        include = variant.get("include", ())
        exclude = variant.get("exclude", ())
        best_all, best_any = _solve(data, scenarios, include=include, exclude=exclude, limit=limit)
        solved.append({"name": variant["name"], "include": list(include), "exclude": list(exclude),
                       "best_all": best_all, "best_any": best_any})
    rows = []
    for entry in solved:
        if entry["best_all"] is None:
            rows.append({"name": entry["name"], "include": entry["include"], "exclude": entry["exclude"],
                         "feasible": False, "expected": None, "scenarios": [],
                         "diagnosis": _diagnose(data, scenarios, entry["best_any"],
                                                entry["include"], entry["exclude"])})
            continue
        assessments = entry["best_all"]["assessments"]
        entries = [(scenario["weight"], assessments[scenario["name"]]["result"]) for scenario in scenarios]
        rows.append({"name": entry["name"], "include": entry["include"], "exclude": entry["exclude"],
                     "feasible": True, "selection": _plan_selection(entry["best_all"]["plan"]),
                     "expected": _expected(entries),
                     "scenarios": [_scenario_summary(scenario["name"], scenario["weight"],
                                                     assessments[scenario["name"]])
                                   for scenario in scenarios]})
    baseline = rows[0]
    for row in rows:
        row["delta_vs_baseline"] = _delta(baseline, row, scenarios)
    return {"resource_id": resource_basis(data), "analysis_id": analysis_basis(data),
            "scenario_names": [s["name"] for s in scenarios], "variants": rows}


def _metrics(row):
    if not row["feasible"] or row["expected"] is None:
        return None
    weight = row["expected"]["weight_covered"]
    if weight <= 0:
        return None
    idle_capacity, idle_grade = {}, {}
    for scenario in row["scenarios"]:
        if not scenario["admissible"]:
            continue
        scale = scenario["weight"] / weight
        for machine, minutes in scenario["idle_capacity"].items():
            idle_capacity[machine] = idle_capacity.get(machine, 0.0) + scale * minutes
        for grade, mass in scenario["idle_grade_kg"].items():
            idle_grade[grade] = idle_grade.get(grade, 0.0) + scale * mass
    return {"net_cents": row["expected"]["net_cents"],
            "contribution_cents": row["expected"]["contribution_cents"],
            "idle_capacity": idle_capacity, "idle_grade_kg": idle_grade,
            "shortage_count": sum(len(scenario["shortages"]) for scenario in row["scenarios"]
                                  if scenario["admissible"])}


def _delta(baseline, row, scenarios):
    left, right = _metrics(baseline), _metrics(row)
    if left is None or right is None:
        return {"comparable": False,
                "reason": "基准或比较方案不可行" if left is None else "比较方案不可行"}
    changed = [machine for machine in left["idle_capacity"]
               if abs(right["idle_capacity"].get(machine, 0.0) - left["idle_capacity"][machine]) > EPS]
    return {"comparable": True,
            "net_cents": round(right["net_cents"] - left["net_cents"], 6),
            "contribution_cents": round(right["contribution_cents"] - left["contribution_cents"], 6),
            "idle_capacity": {machine: round(right["idle_capacity"].get(machine, 0.0) - value, 6)
                              for machine, value in left["idle_capacity"].items()},
            "idle_grade_kg": {grade: round(right["idle_grade_kg"].get(grade, 0.0) - value, 6)
                              for grade, value in left["idle_grade_kg"].items()},
            "shortage_count": right["shortage_count"] - left["shortage_count"],
            "fixed_cost_changed": False,
            "changed_constraints": sorted(set(changed) | {
                grade for grade, value in left["idle_grade_kg"].items()
                if abs(right["idle_grade_kg"].get(grade, 0.0) - value) > EPS})}


def bottlenecks(data, selection, book=None):
    """解释制约收益的真正资源：受限等级/机时及其边际价值估算。

    边际价值是按当前报价和剩余需求粗算的上限，只用于排序瓶颈，不进入收益口径。
    """
    result = evaluate(data, selection, book)
    supply = resources(data)
    used_grade, used_capacity = result["usage_grade_kg"], result["usage_capacity"]
    taken = {item["offer_id"]: item["kg"] for item in selection}
    binding, slack = [], []
    for grade, total in supply["grade_kg"].items():
        share = used_grade.get(grade, 0.0) / total if total else 0.0
        alternatives = substitute_grades(data, grade, supply["grade_kg"])
        entry = {"kind": "grade", "resource": grade, "used_share": round(share, 6),
                 "idle_kg": round(result["idle_grade_kg"].get(grade, 0.0), 6),
                 "alternative_grades": alternatives}
        if share >= 0.95 - EPS:
            binding.append(entry)
        else:
            slack.append(entry)
    for machine, total in supply["capacity_minutes"].items():
        share = used_capacity.get(machine, 0.0) / total if total else 0.0
        entry = {"kind": "capacity", "resource": machine, "used_share": round(share, 6),
                 "idle_minutes": round(result["idle_capacity"].get(machine, 0.0), 6)}
        if share >= 0.95 - EPS:
            binding.append(entry)
        else:
            slack.append(entry)
    for entry in binding:
        entry["shadow_cents_per_unit"] = round(_shadow(data, entry, taken, book, result), 6)
    binding.sort(key=lambda row: (-row["shadow_cents_per_unit"], row["kind"], row["resource"]))
    return {"feasible": result["feasible"], "binding": binding, "slack": slack,
            "conflicts": result["conflicts"],
            "explanation": _explain(binding, result)}


def _shadow(data, entry, taken, book, result):
    if book is None:
        book = PriceBook(data)
    best = 0.0
    for offer in data["offers"]:
        product = data["products"][offer["product"]]
        if entry["kind"] == "grade":
            if not compatible(data, entry["resource"], product["input_grade"]):
                continue
            output_per_unit = float(product["conversion_yield"])
            headroom = max(0.0, max(book.options(offer) or [0.0]) - taken.get(offer["offer_id"], 0.0))
            if headroom <= EPS:
                continue
            best = max(best, (book.price(offer) - product["variable_cents_per_kg"]) * output_per_unit)
        else:
            per_kg = product["minutes_per_kg"].get(entry["resource"], 0.0)
            if per_kg <= 0:
                continue
            headroom = max(0.0, max(book.options(offer) or [0.0]) - taken.get(offer["offer_id"], 0.0))
            if headroom <= EPS:
                continue
            best = max(best, (book.price(offer) - product["variable_cents_per_kg"]) / per_kg)
    return max(0.0, best)


def _explain(binding, result):
    if not result["feasible"]:
        parts = [row["reason"] for row in result["conflicts"]]
        return "当前组合不可行：" + "；".join(parts)
    if not binding:
        return "当前组合未触及原料或机时上限；收益受需求与报价约束，而不是产能。"
    parts = []
    for row in binding:
        if row["kind"] == "capacity":
            parts.append(f"{row['resource']} 机时已用 {row['used_share'] * 100:.1f}%，"
                         f"每增加 1 分钟约可增边际收益 {row['shadow_cents_per_unit']:.2f} 分")
        else:
            alt = "、".join(row["alternative_grades"]) or "无"
            parts.append(f"{row['resource']} 级已用 {row['used_share'] * 100:.1f}%（可降级来源：{alt}），"
                         f"每增加 1 kg 约可增边际收益 {row['shadow_cents_per_unit']:.2f} 分")
    return "真正受限的是：" + "；".join(parts) + "。"


def unchanged_costs(data, baseline_selection, variant_selection, book=None):
    """换方案也不会改变的成本：固定成本与单位变动费率；只有总量随组合变化。"""
    if book is None:
        book = PriceBook(data)
    left = evaluate(data, baseline_selection, book)
    right = evaluate(data, variant_selection, book)
    fixed = data.get("fixed_cents", 0)
    return {
        "fixed_cents": fixed,
        "fixed_cost_note": "固定成本在两个方案中相同，不因换方案而增减，也不进入逐单贡献。",
        "unit_variable_cents_per_kg": {product: row["variable_cents_per_kg"]
                                       for product, row in data["products"].items()},
        "unit_cost_note": "单位变动成本由基础数据给定，不随方案改变；变动成本总额只因交付量与品种结构变化。",
        "variable_cents": {"baseline": left["variable_cents"], "variant": right["variable_cents"],
                           "delta": round(right["variable_cents"] - left["variable_cents"], 6)},
        "net_cents": {"baseline": left["net_cents"], "variant": right["net_cents"],
                      "delta": round(right["net_cents"] - left["net_cents"], 6)},
        "feasible": {"baseline": left["feasible"], "variant": right["feasible"]},
    }


def assets_report(data, include=(), exclude=()):
    """一次生成推荐方案、业务员指定方案的比较、瓶颈与不变成本，全部只读。"""
    from demand import demand_basis

    recommendation = recommend(data, include=include, exclude=exclude)
    variants = [{"name": "推荐组合", "include": [], "exclude": []}]
    if include or exclude:
        variants.append({"name": "业务员指定", "include": list(include), "exclude": list(exclude)})
    comparison = compare(data, variants)
    report = {"demand_id": demand_basis(data), "analysis_id": analysis_basis(data),
              "recommendation": recommendation, "comparison": comparison,
              "unchanged_costs": None, "bottlenecks": None,
              "as_of_note": "结果基于当前已知记录；采纳时若基础数据变化会重新判断，不会沿用本建议。"}
    if recommendation["feasible"]:
        report["bottlenecks"] = bottlenecks(data, recommendation["selection"])
        chosen = next((row for row in comparison["variants"] if row["name"] == "业务员指定"), None)
        if chosen and chosen["feasible"]:
            report["unchanged_costs"] = unchanged_costs(data, recommendation["selection"], chosen["selection"])
        else:
            report["unchanged_costs"] = unchanged_costs(data, recommendation["selection"],
                                                        recommendation["selection"])
    return report


def adopt(data, recommendation, expected_resource_id):
    """采纳推荐/比较方案。

    分析时的原料/能力、需求/价格或固定成本与当前不一致，或按当前数据重新核对
    不可行时，拒绝写入并提示重新分析，避免把过期建议直接变成订单。
    """
    if recommendation.get("resource_id") != expected_resource_id:
        raise ValueError("分析依据与采纳依据不一致")
    if recommendation.get("analysis_id") != analysis_basis(data):
        raise ValueError("基础数据已变更，请重新分析后再采纳")
    if not recommendation.get("feasible") or recommendation.get("robust") is False:
        raise ValueError("该方案不可执行，不能采纳")
    selection = recommendation.get("selection") or []
    proposed = [{"offer_id": item["offer_id"], "kg": item["kg"]} for item in selection if item["kg"] > 0]
    taken = {booking["offer_id"] for booking in data.get("bookings", [])}
    repeated = sorted(taken & {row["offer_id"] for row in proposed})
    if repeated:
        raise ValueError("方案中的意向单已承诺：" + "、".join(repeated))
    result = accept_commitments(data, proposed, expected_resource_id)
    return {**result, "analysis_resource_id": recommendation["resource_id"],
            "rechecked_resource_id": resource_basis(data), "selection": proposed}
