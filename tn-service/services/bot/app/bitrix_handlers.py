import asyncio
from typing import Any, Dict, Tuple

from app.db import get_doc, set_confirmed, set_bitrix_result
from app.bitrix_client import send_to_bitrix_sync


def _safe_get(d: Dict[str, Any], path: Tuple[str, ...], default=""):
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur


def _build_bitrix_text(doc_id: int, ocr: Dict[str, Any]) -> str:
    base_name = _safe_get(ocr, ("loading_base", "name"))
    base_addr = _safe_get(ocr, ("loading_base", "address"))
    date_val  = _safe_get(ocr, ("loading_date", "value"))
    driver    = _safe_get(ocr, ("driver_name", "value"))
    product   = _safe_get(ocr, ("product_type", "value"))

    kg   = _safe_get(ocr, ("weight_total", "kg"))
    tons = _safe_get(ocr, ("weight_total", "value_tons"))
    edited = bool(_safe_get(ocr, ("weight_total", "edited_by_user"), default=False))

    # ПРАВИЛО: если вес редактировали вручную -> отправляем только кг (без тонн)
    weight_line = ""
    if edited and kg not in ("", None):
        weight_line = f"{kg} кг"
    else:
        if kg not in ("", None):
            weight_line = f"{kg} кг"
            if tons not in ("", None):
                weight_line += f" (≈ {tons} т)"
        elif tons not in ("", None):
            weight_line = f"{tons} т"

    return (
        f"✅ Транспортная накладная #{doc_id}\n"
        f"Базис погрузки: {base_name}\n"
        f"Адрес: {base_addr}\n"
        f"Дата погрузки: {date_val}\n"
        f"ФИО водителя: {driver}\n"
        f"Вес: {weight_line}\n"
        f"Вид продукции: {product}\n"
    ).strip()


async def handle_bitrix_callback(update, context) -> bool:
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if not (data.startswith("ok:") or data.startswith("retry:")):
        return False

    cmd, doc_id_s = data.split(":", 1)
    try:
        doc_id = int(doc_id_s)
    except Exception:
        await query.edit_message_text("❌ Некорректный doc_id")
        return True

    doc = get_doc(doc_id)
    if not doc:
        await query.edit_message_text("❌ Документ не найден в БД")
        return True

    ocr_data = doc.get("ocr_data") or {}
    text = _build_bitrix_text(doc_id, ocr_data)

    if cmd == "ok":
        set_confirmed(doc_id)

    photo_path = doc.get("photo_path")
    ok, resp, err, payload_for_db = await asyncio.to_thread(send_to_bitrix_sync, text, photo_path)

    if ok:
        set_bitrix_result(doc_id, "sent", payload_for_db, resp, "")
        kb = {"inline_keyboard": [[{"text": "✅ Отправлено в Битрикс", "callback_data": "noop"}]]}
        await query.edit_message_text(query.message.text + "\n\n✅ Отправлено в Битрикс24", reply_markup=kb)
    else:
        set_bitrix_result(doc_id, "error", payload_for_db, resp, err)
        kb = {
            "inline_keyboard": [
                [{"text": "🔁 Повторить отправку", "callback_data": f"retry:{doc_id}"}],
                [{"text": "✏️ Исправить", "callback_data": f"edit:{doc_id}"}],
                [{"text": "📸 Переснять", "callback_data": f"reshoot:{doc_id}"}],
            ]
        }
        await query.edit_message_text(query.message.text + f"\n\n❌ Ошибка отправки в Битрикс: {err}", reply_markup=kb)

    return True
