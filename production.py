"""原料分级、降级使用与产线能力。

本模块是所有资源判断的唯一入口：销售组合分析（``portfolio``）与实际承诺校验
（``costing.check_commitments``）都调用 ``allocate``，因此两者对同一批原料和
同一组订单给出相同的消耗、闲置与短缺口径。
"""
from records import fingerprint, quantity

EPS = 1e-8


def resources(data):
    grades = {}
    total = 0
    for row in data["raw_lots"]:
        mass = quantity(row["kg"])
        fractions = row["yield_fraction"]
        if sum(quantity(value) for value in fractions.values()) > 1 + 1e-9:
            raise ValueError("分级产出超过原料")
        total += mass
        for grade, fraction in fractions.items():
            grades[grade] = grades.get(grade, 0) + mass * quantity(fraction)
    result = {"raw_kg": total, "grade_kg": grades,
              "capacity_minutes": {key: quantity(value) for key, value in data["capacity_minutes"].items()}}
    return {**result, "resource_id": resource_basis(data)}


def resource_basis(data):
    """原料与能力依据（含分级损耗、降级方向、加工得率），用于判断建议是否过期。"""
    return fingerprint({
        "raw_lots": data.get("raw_lots", []),
        "capacity_minutes": data.get("capacity_minutes", {}),
        "downgrade": data.get("downgrade", {}),
        "products": data.get("products", {}),
    })


def process_usage(data, product, kg):
    if product not in data["products"]:
        raise ValueError("未知加工品")
    definition = data["products"][product]
    mass = quantity(kg)
    ratio = float(definition["conversion_yield"])
    if not 0 < ratio <= 1:
        raise ValueError("加工得率无效")
    return {"input_grade": definition["input_grade"], "input_kg": mass / ratio,
            "capacity_minutes": {key: value * mass for key, value in definition["minutes_per_kg"].items()}}


def compatible(data, source_grade, requested_grade):
    return source_grade == requested_grade or requested_grade in data["downgrade"].get(source_grade, [])


def substitute_grades(data, requested_grade, available_grades):
    """可投入到 ``requested_grade`` 的其他等级，按等级名排序；降级关系有方向。"""
    return [grade for grade in sorted(available_grades)
            if grade != requested_grade and compatible(data, grade, requested_grade)]


class _FlowGraph:
    def __init__(self, size):
        self.graph = [[] for _ in range(size)]

    def add_edge(self, source, target, capacity):
        forward = [target, float(capacity), len(self.graph[target])]
        backward = [source, 0.0, len(self.graph[source])]
        self.graph[source].append(forward)
        self.graph[target].append(backward)
        return forward

    def max_flow(self, source, sink):
        total = 0.0
        size = len(self.graph)
        while True:
            level = [-1] * size
            level[source] = 0
            queue = [source]
            for node in queue:
                for edge in self.graph[node]:
                    if edge[1] > EPS and level[edge[0]] < 0:
                        level[edge[0]] = level[node] + 1
                        queue.append(edge[0])
            if level[sink] < 0:
                return total
            cursor = [0] * size

            def push(node, available):
                if node == sink:
                    return available
                while cursor[node] < len(self.graph[node]):
                    edge = self.graph[node][cursor[node]]
                    target, capacity, reverse = edge
                    if capacity > EPS and level[target] == level[node] + 1:
                        sent = push(target, min(available, capacity))
                        if sent > EPS:
                            edge[1] -= sent
                            self.graph[target][reverse][1] += sent
                            return sent
                    cursor[node] += 1
                return 0.0

            while True:
                sent = push(source, float("inf"))
                if sent <= EPS:
                    break
                total += sent


def _demand_rows(data, demands):
    """把订单交付量转换成等级投入需求与机时需求，并拒绝重复意向单。"""
    from demand import offer_row

    rows, seen = [], set()
    for demand in demands:
        offer_id = demand["offer_id"]
        if offer_id in seen:
            raise ValueError("同一意向单重复承诺")
        seen.add(offer_id)
        mass = quantity(demand["kg"])
        if mass <= 0:
            continue
        product = demand.get("product") or offer_row(data, offer_id)["product"]
        usage = process_usage(data, product, mass)
        rows.append({"offer_id": offer_id, "product": product, "kg": mass,
                     "input_grade": usage["input_grade"], "input_kg": usage["input_kg"],
                     "capacity_minutes": usage["capacity_minutes"]})
    return rows


def _allocate_rows(data, rows, grades, capacity):
    shortages = []
    for row in rows:
        for machine, minutes in row["capacity_minutes"].items():
            capacity[machine] = capacity.get(machine, 0.0) - minutes
    for machine, minutes in capacity.items():
        if minutes < -EPS:
            shortages.append({"kind": "capacity", "resource": machine, "short": -minutes})

    grade_names = sorted(grades)
    grade_nodes = {grade: index + 1 for index, grade in enumerate(grade_names)}
    demand_start = 1 + len(grade_names)
    sink = demand_start + len(rows)
    network = _FlowGraph(sink + 1)
    source = 0
    for grade in grade_names:
        network.add_edge(source, grade_nodes[grade], grades[grade])
    demand_edges = []
    for offset, row in enumerate(rows):
        node = demand_start + offset
        network.add_edge(node, sink, row["input_kg"])
        demand_edges.append([])
        for grade in grade_names:
            if compatible(data, grade, row["input_grade"]):
                edge = network.add_edge(grade_nodes[grade], node, row["input_kg"])
                demand_edges[offset].append((grade, edge))
    total_demand = sum(row["input_kg"] for row in rows)
    flow = network.max_flow(source, sink)
    if flow < total_demand - EPS:
        for offset, row in enumerate(rows):
            # 反向边容量即该等级边实际流过的数量。
            served = sum(network.graph[edge[0]][edge[2]][1] for _, edge in demand_edges[offset])
            short = row["input_kg"] - served
            if short > EPS:
                shortages.append({"offer_id": row["offer_id"], "kind": "grade",
                                  "resource": row["input_grade"], "short": short})

    allocations = []
    usage_grade = {grade: 0.0 for grade in grade_names}
    for offset, row in enumerate(rows):
        consumed = {}
        for grade, edge in demand_edges[offset]:
            sent = network.graph[edge[0]][edge[2]][1]
            if sent > EPS:
                consumed[grade] = sent
                usage_grade[grade] += sent
        allocations.append({"offer_id": row["offer_id"], "consumed_grade_kg": consumed})
    for grade in grade_names:
        grades[grade] = max(0.0, grades[grade] - usage_grade[grade])

    usage_capacity = {machine: 0.0 for machine in capacity}
    for row in rows:
        for machine, minutes in row["capacity_minutes"].items():
            usage_capacity[machine] = usage_capacity.get(machine, 0.0) + minutes
    return {"feasible": not shortages, "shortages": shortages, "allocations": allocations,
            "remaining_grade_kg": grades, "remaining_capacity": capacity,
            "usage_grade_kg": usage_grade, "usage_capacity": usage_capacity}


def allocate(data, demands):
    """在已有承诺之后分配新增订单；已有承诺先占用原料与机时。"""
    bookings = list(data.get("bookings", []))
    booking_rows = _demand_rows(data, bookings)
    rows = booking_rows + _demand_rows(data, demands)
    basis = resources(data)
    result = _allocate_rows(data, rows, dict(basis["grade_kg"]), dict(basis["capacity_minutes"]))
    result["allocations"] = result["allocations"][len(booking_rows):]
    return result


def check_with_supply(data, demands, grade_supply, capacity_supply):
    """不考虑已有承诺、使用给定剩余供应做可行性核对（组合搜索使用）。"""
    grades = {grade: quantity(value) for grade, value in grade_supply.items()}
    capacity = {machine: quantity(value) for machine, value in capacity_supply.items()}
    rows = _demand_rows(data, demands)
    return _allocate_rows(data, rows, grades, capacity)
