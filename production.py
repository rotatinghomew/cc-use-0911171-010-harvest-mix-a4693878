from records import quantity, fingerprint


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
            grades[grade] = grades.get(grade, 0) + mass * fraction
    result = {"raw_kg": total, "grade_kg": grades,
              "capacity_minutes": {key: quantity(value) for key, value in data["capacity_minutes"].items()}}
    return {**result, "resource_id": fingerprint(result)}


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
