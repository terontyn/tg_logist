import os
import json
import logging
import redis

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

from app.db import set_status, update_field, get_doc

# ---- LOGGING (убираем шум httpx, делаем понятные логи) ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("tn_bot")

# глушим спам getUpdates
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

rds = redis.Redis.from_url(REDIS_URL, decode_responses=True)
EDIT_STATE = {}  # chat_id -> {"doc_id":..., "field":...}


def build_main_keyboard(doc_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok:{doc_id}")],
        [InlineKeyboardButton("✏️ Исправить", callback_data=f"edit:{doc_id}")],
        [InlineKeyboardButton("📸 Переснять", callback_data=f"reshoot:{doc_id}")],
    ])


def build_edit_fields_keyboard(doc_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Базис погрузки", callback_data=f"field:{doc_id}:base_name")],
        [InlineKeyboardButton("Дата погрузки", callback_data=f"field:{doc_id}:loading_date")],
        [InlineKeyboardButton("ФИО водителя", callback_data=f"field:{doc_id}:driver_name")],
        [InlineKeyboardButton("Вес (кг)", callback_data=f"field:{doc_id}:weight_kg")],
        [InlineKeyboardButton("Вид продукции", callback_data=f"field:{doc_id}:product_type")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"back:{doc_id}")],
    ])


def format_doc_for_driver(doc):
    data = doc["ocr_data"] or {}

    base = (data.get("loading_base") or {}).get("name") or "—"
    addr = (data.get("loading_base") or {}).get("address")
    dt = (data.get("loading_date") or {}).get("value") or "—"
    driver = (data.get("driver_name") or {}).get("value") or "—"
    product = (data.get("product_type") or {}).get("value") or "—"

    wt = data.get("weight_total") or {}
    kg = wt.get("kg")
    t = wt.get("value")

    if kg is not None:
        wt_str = f"{int(kg):,}".replace(",", " ") + " кг"
        if t is not None:
            wt_str += f" (≈ {str(t).replace('.', ',')} т)"
    else:
        wt_str = f"{t} т" if t is not None else "—"

    lines = [f"✅ Накладная #{doc['id']}"]
    lines.append(f"Базис погрузки\t{base}")
    if addr:
        lines.append(f"Адрес\t{addr}")
    lines.append(f"Дата погрузки\t{dt}")
    lines.append(f"ФИО водителя\t{driver}")
    lines.append(f"Вес продукции\t{wt_str}")
    lines.append(f"Вид продукции\t{product}")
    return "\n".join(lines)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("❌ Bot error: %s", context.error)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("✅ /start chat_id=%s user_id=%s", update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text("Отправьте фото/файл накладной (ТН/ТТН).")


async def enqueue_task(chat_id: int, file_id: str):
    task = {"type": "photo", "chat_id": chat_id, "file_id": file_id}
    rds.rpush("tasks", json.dumps(task, ensure_ascii=False))
    log.info("✅ Enqueued task chat_id=%s file_id=%s", chat_id, file_id)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    file_id = update.message.photo[-1].file_id
    log.info("📩 UPDATE type=photo chat_id=%s file_id=%s", chat_id, file_id)
    await enqueue_task(chat_id, file_id)
    await update.message.reply_text("Фото принято. Поставил в очередь на распознавание.")


async def on_document_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc = update.message.document
    file_id = doc.file_id
    log.info("📩 UPDATE type=document_image chat_id=%s file_id=%s name=%s", chat_id, file_id, doc.file_name)
    await enqueue_task(chat_id, file_id)
    await update.message.reply_text("Файл-изображение принято. Поставил в очередь на распознавание.")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    chat_id = q.message.chat_id
    log.info("📩 UPDATE type=callback chat_id=%s data=%s", chat_id, data)

    if data.startswith("ok:"):
        doc_id = int(data.split(":")[1])
        set_status(doc_id, "confirmed")
        await q.message.reply_text(f"✅ Принято. Накладная #{doc_id} подтверждена.")
        return

    if data.startswith("reshoot:"):
        doc_id = int(data.split(":")[1])
        set_status(doc_id, "need_reshoot")
        await q.message.reply_text(
            f"📸 Ок. Переснимите накладную #{doc_id} и отправьте новое фото.\n"
            f"Совет: без бликов, сверху, чтобы был виден низ с ФИО."
        )
        return

    if data.startswith("edit:"):
        doc_id = int(data.split(":")[1])
        await q.message.reply_text("Что исправить?", reply_markup=build_edit_fields_keyboard(doc_id))
        return

    if data.startswith("back:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        if not doc:
            await q.message.reply_text("Документ не найден.")
            return
        await q.message.reply_text(format_doc_for_driver(doc), reply_markup=build_main_keyboard(doc_id))
        return

    if data.startswith("field:"):
        _, doc_id_s, field = data.split(":", 2)
        doc_id = int(doc_id_s)
        EDIT_STATE[chat_id] = {"doc_id": doc_id, "field": field}

        prompts = {
            "base_name": "Введите Базис погрузки:",
            "loading_date": "Введите Дату погрузки (03.02.2026 или 2026-02-03):",
            "driver_name": "Введите ФИО водителя:",
            "weight_kg": "Введите Вес в кг (например 27328):",
            "product_type": "Введите Вид продукции:",
        }
        await q.message.reply_text(prompts.get(field, "Введите новое значение:"))
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    txt = (update.message.text or "").strip()
    log.info("📩 UPDATE type=text chat_id=%s text=%r", chat_id, txt[:200])

    st = EDIT_STATE.get(chat_id)
    if not st:
        return

    doc_id = st["doc_id"]
    field = st["field"]

    try:
        update_field(doc_id, field, txt)
        set_status(doc_id, "edited")
        log.info("✅ Saved edit doc_id=%s field=%s", doc_id, field)
    except Exception as e:
        log.exception("❌ Save edit failed")
        await update.message.reply_text(f"❌ Не смог сохранить: {e}")
        return
    finally:
        EDIT_STATE.pop(chat_id, None)

    doc = get_doc(doc_id)
    if not doc:
        await update.message.reply_text("Документ не найден после сохранения.")
        return

    await update.message.reply_text(
        "✅ Сохранил исправление.\n\n" + format_doc_for_driver(doc),
        reply_markup=build_main_keyboard(doc_id),
    )


def main():
    log.info("✅ Bot booting...")

    # Проверка Redis на старте (как в worker)
    try:
        rds.ping()
        log.info("✅ Connected to Redis")
    except Exception as e:
        log.error("❌ Redis error: %s", e)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(error_handler)

    log.info("✅ Handlers registered")
    log.info("Bot started (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
