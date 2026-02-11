def _g(d, *path, default=""):
    cur = d or {}
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur

def format_for_driver(doc_id: int, data: dict, ok: bool, reason: str, conf: float) -> str:
    base_name = _g(data, "loading_base", "name")
    base_addr = _g(data, "loading_base", "address")
    base_city = _g(data, "loading_base", "city")

    date_val  = _g(data, "loading_date", "value")
    driver    = _g(data, "driver_name", "value")
    product   = _g(data, "product_type", "value")

    kg   = _g(data, "weight_total", "kg")
    tons = _g(data, "weight_total", "value_tons")

    # вес красиво
    weight = ""
    if kg not in ("", None):
        try:
            weight = f"{int(kg):,}".replace(",", " ") + " кг"
        except Exception:
            weight = f"{kg} кг"
        if tons not in ("", None):
            weight += f" (≈ {tons} т)"
    elif tons not in ("", None):
        weight = f"{tons} т"

    # базис одной строкой, город в скобках если есть
    base_line = base_name or ""
    city = base_city or ""
    if not city and isinstance(base_addr, str):
        # грубая эвристика: если адрес начинается с "г. <город>" — город в скобки
        import re
        m = re.search(r"\bг\.\s*([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z\- ]{2,})", base_addr)
        if m:
            city = m.group(1).strip()
    if city:
        base_line = f"{base_line} ({city})" if base_line else f"({city})"

    # Сообщение ТОЛЬКО с данными (без "точность/причина")
    lines = []
    lines.append(f"✅ Документ распознан (#{doc_id})")
    lines.append("")
    lines.append(f"Базис погрузки\t{base_line}".rstrip())
    if base_addr:
        lines.append(f"Адрес\t{base_addr}".rstrip())
    lines.append(f"Дата погрузки\t{date_val}".rstrip())
    lines.append(f"ФИО водителя\t{driver}".rstrip())
    lines.append(f"Вес продукции\t{weight}".rstrip())
    lines.append(f"Вид продукции\t{product}".rstrip())

    return "\n".join(lines).strip()
