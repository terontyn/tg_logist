import json
import time
import redis

from app.config import REDIS_URL
from app.db import init_db, insert_received, update_ocr
from app.telegram_client import download_photo, send_message
from app.ocr import ocr_two_pass
from app.validation import validate
from app.formatting import format_for_driver


def get_redis():
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=30,
        retry_on_timeout=True,
        health_check_interval=30,
    )


def main():
    print("✅ Worker booting...")

    init_db()
    print("✅ DB initialized (table transport_documents ready)")

    rds = None
    print("Worker started. Waiting for tasks...")

    while True:
        try:
            if rds is None:
                rds = get_redis()
                rds.ping()
                print("✅ Connected to Redis")

            item = rds.blpop("tasks", timeout=10)
            if not item:
                continue

            task = json.loads(item[1])
            print("📩 Got task:", task)

            if task.get("type") != "photo":
                print("ℹ️ Skip non-photo task")
                continue

            chat_id = int(task["chat_id"])
            file_id = task["file_id"]

            print("⬇️ Downloading photo...")
            photo_path = download_photo(file_id)
            print("✅ Photo downloaded:", photo_path)

            print("💾 Inserting DB record...")
            doc_id = insert_received(chat_id, file_id, photo_path)
            print("✅ DB doc_id:", doc_id)

            print("🧠 OCR start (OpenAI gpt-4o, two-pass)...")
            data = ocr_two_pass(photo_path)  # <-- ВАЖНО: дальше используем единое имя data
            raw = json.dumps(data, ensure_ascii=False)  # <-- RAW для сохранения в БД (строкой)
            print("✅ OCR done")

            print("🔎 Validating OCR result...")
            ok, reason, conf = validate(data)
            print("✅ Validation:", ok, reason, conf)

            status = "ocr_ok" if ok else "ocr_error"
            update_ocr(doc_id, data, raw, conf, status, reason)

            msg = format_for_driver(doc_id, data, ok, reason, conf)

            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Подтвердить", "callback_data": f"ok:{doc_id}"}],
                    [{"text": "✏️ Исправить", "callback_data": f"edit:{doc_id}"}],
                    [{"text": "📸 Переснять", "callback_data": f"reshoot:{doc_id}"}],
                ]
            }

            print("📨 Sending message to Telegram...")
            try:
                send_message(chat_id, msg, reply_markup=keyboard)
                print("✅ Sent to Telegram")
            except Exception as e:
                print(f"❌ Send to Telegram failed: {repr(e)}")

        except redis.exceptions.ConnectionError as e:
            print(f"⚠️ Redis connection error: {e}. Reconnecting in 2s...")
            rds = None
            time.sleep(2)

        except Exception as e:
            print(f"❌ Worker error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
