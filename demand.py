"""意向需求、报价响应与整包装交付条件。

价格与数量不是独立条件：同一市场情景下各产品价格一起变动，报价又决定客户愿意
接受的追加量。``PriceBook`` 把二者绑定在一起，避免把不同情景的最乐观条件拼成
一个不存在的方案。
"""
from records import quantity

EPS = 1e-9


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
        if quantity(row["step_kg"]) <= 0:
            raise ValueError("整包装步长应为正数")
        if quantity(row["price_cents_per_kg"]) <= 0:
            raise ValueError("报价应为正数")
        if quantity(row["price_sensitivity"]) < 0:
            raise ValueError("价格响应系数应为非负数")
        result.append({**row, "min_kg": minimum, "max_kg": maximum, "step_kg": quantity(row["step_kg"])})
    return result


def offer_row(data, offer_id):
    rows = {row["offer_id"]: row for row in offers(data)}
    if offer_id not in rows:
        raise ValueError("未知意向单")
    return rows[offer_id]


def validate_quantity(data, offer_id, kg):
    row = offer_row(data, offer_id)
    mass = quantity(kg)
    if mass and not row["min_kg"] <= mass <= row["max_kg"]:
        raise ValueError("交付量不符合客户条件")
    if abs(mass / row["step_kg"] - round(mass / row["step_kg"])) > 1e-9:
        raise ValueError("交付量不符合整包装单位")
    return {**row, "accepted_kg": mass}


def quoted_volume(data, offer_id, price_cents_per_kg):
    """报价变化后的客户需求上限；降价放宽追加量，提价收缩。"""
    row = offer_row(data, offer_id)
    price = quantity(price_cents_per_kg)
    change = (price - row["price_cents_per_kg"]) / row["price_cents_per_kg"]
    return max(0, row["max_kg"] * (1 - change * row["price_sensitivity"]))


def quantity_options(data, offer_id, volume_cap=None):
    """可执行的整包装交付量；不接单的 0 由组合层显式表示。"""
    row = offer_row(data, offer_id)
    limit = row["max_kg"] if volume_cap is None else min(row["max_kg"], quantity(volume_cap))
    low = int(-(-row["min_kg"] // row["step_kg"]))
    if low * row["step_kg"] < row["min_kg"] - EPS:
        low += 1
    high = int(limit / row["step_kg"] + EPS)
    result = []
    for multiple in range(low, high + 1):
        mass = round(multiple * row["step_kg"], 9)
        if row["min_kg"] - EPS <= mass <= limit + EPS:
            result.append(mass)
    return result


def demand_basis(data):
    """需求与价格依据；用于判断分析时的报价、数量和交付条件是否已过期。"""
    from records import fingerprint

    return fingerprint({
        "offers": data.get("offers", []),
        "market_scenarios": data.get("market_scenarios", []),
    })


def market_scenarios(data):
    """市场情景：每个情景给出所有产品的价格因子，权重归一化后用于比较。"""
    rows = data.get("market_scenarios") or [{"name": "base", "weight": 1.0}]
    products = sorted(data["products"])
    result, total = [], 0.0
    for row in rows:
        weight = quantity(row.get("weight", 1.0))
        if weight <= 0:
            raise ValueError("市场情景权重应为正数")
        total += weight
        factors = {product: quantity(row.get(f"{product}_price_factor", 1.0)) for product in products}
        result.append({"name": row["name"], "weight": weight, "price_factors": factors})
    if total <= 0:
        raise ValueError("市场情景权重合计应为正数")
    for row in result:
        row["weight"] = row["weight"] / total
    if abs(sum(row["weight"] for row in result) - 1) > 1e-9:
        raise ValueError("市场情景权重归一化失败")
    return result


class PriceBook:
    """一个市场情景下的报价；单价与可接受追加量由同一次报价共同决定。"""

    def __init__(self, data, factors=None):
        self.data = data
        self.factors = {product: 1.0 for product in data["products"]} if factors is None else dict(factors)

    def price(self, offer):
        base = quantity(offer["price_cents_per_kg"])
        return max(0.0, base * quantity(self.factors.get(offer["product"], 1.0)))

    def options(self, offer):
        quoted = quoted_volume(self.data, offer["offer_id"], self.price(offer))
        return quantity_options(self.data, offer["offer_id"], quoted)

    def revenue(self, offer, kg):
        return quantity(kg) * self.price(offer)
