import re
from datetime import datetime
from typing import Optional

from app.base_directory import get_or_create_canonical


def _title_fio(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return "—"
    letters = [c for c in s if c.isalpha()]
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / max(1, len(letters))
        if upper_ratio > 0.8:
            s = s.lower().title()
    return s


def normalize_date(val: str | None) -> str:
    if not val:
        return "—"
    s = str(val).strip()
    if not s:
        return "—"
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return s


def normalize_base(name: str | None, address: str | None) -> str:
    canonical, city = get_or_create_canonical(name, address)
    if city:
        return f"{canonical} ({city})"
    return canonical


def _format_weight(data: dict) -> str:
    wt_total = data.get("weight_total") or {}
    kg = wt_total.get("kg")
    t = wt_total.get("value")
    if kg is not None:
        try:
            kg_int = int(str(kg).replace(" ", "").replace("\xa0", ""))
        except Exception:
            kg_int = None
        if kg_int is not None:
            kg_str = f"{kg_int:,}".replace(",", " ")
            if t is None:
                t = round(kg_int / 1000.0, 3)
            t_str = str(t).replace(".", ",")
            return f"{kg_str} кг (≈ {t_str} т)"

    w = data.get("weight") or {}
    val = w.get("value")
    unit = w.get("unit") or "t"
    if val is None:
        return "—"
    return f"{str(val).replace('.', ',')} {unit}"


def format_for_driver(doc_id: int, ocr_data: dict, ok: bool, reason: str | None, confidence: float | None) -> str:
    data = ocr_data or {}

    base_obj = data.get("loading_base") or {}
    base_name = base_obj.get("name") or base_obj.get("value")
    base_addr = base_obj.get("address")
    base = normalize_base(base_name, base_addr)

    raw_dt = (data.get("loading_date") or {}).get("value")
    dt = normalize_date(raw_dt)

    driver_raw = (data.get("driver_name") or {}).get("value")
    driver = _title_fio(driver_raw) if driver_raw else "—"

    product = (data.get("product_type") or {}).get("value") or "—"
    weight_str = _format_weight(data)

    conf_str = f"\nТочность: {round(float(confidence) * 100)}%" if confidence is not None else ""
    if ok:
        header = f"✅ Документ распознан (#{doc_id}){conf_str}"
    else:
        header = f"⚠️ Нужна проверка (#{doc_id}){conf_str}"
        if reason:
            header += f"\nПричина: {reason}"

    return "\n".join([
        header,
        "",
        f"Базис погрузки\t{base}",
        f"Дата погрузки\t{dt}",
        f"ФИО водителя\t{driver}",
        f"Вес продукции\t{weight_str}",
        f"Вид продукции\t{product}",
    ])
