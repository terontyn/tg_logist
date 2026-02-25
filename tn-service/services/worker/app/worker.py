import os, json, time, redis
from app.db import init_db, insert_received, update_ocr
from app.telegram_client import download_photo, send_message
from app.ocr import extract_batch
from app.formatting import format_for_driver

def main():
    init_db()
    rds = redis.Redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    print("✅ Worker started. Batch & GPT-5.2 mode active. Extended logging enabled.")
    
    while True:
        try:
            item = rds.blpop("tasks", timeout=10)
            if not item: continue
            
            task = json.loads(item[1])
            files = task.get("files", [])
            if not files: continue

            chat_id = task["chat_id"]
            print(f"\n" + "="*50)
            print(f"🚀 [WORKER] Новая задача! ID Чата: {chat_id}, Количество файлов: {len(files)}")
            
            print(f"📥 [WORKER] Этап 1: Скачивание файлов из Telegram...")
            paths = [download_photo(fid) for fid in files]
            print(f"✅ [WORKER] Файлы успешно загружены: {paths}")
            
            print(f"🤖 [WORKER] Этап 2: Передача файлов в нейросеть (OCR)...")
            data = extract_batch(paths)
            print(f"✅ [WORKER] Распознавание завершено.")
            
            print(f"💾 [WORKER] Этап 3: Запись результатов в PostgreSQL...")
            doc_id = insert_received(chat_id, ",".join(files), ",".join(paths))
            update_ocr(doc_id, data, json.dumps(data), data.get("confidence", 0), "ocr_ok", "")
            print(f"✅ [WORKER] Создана запись в БД с ID #{doc_id}.")
            
            print(f"✉️ [WORKER] Этап 4: Формирование отчета для Telegram...")
            msg = format_for_driver(doc_id, data, True, "", data.get("confidence", 0))

            kb = {"inline_keyboard": [
                [{"text": "🚚 Ввести перевозчика", "callback_data": f"field:{doc_id}:carrier_name"}],
                [{"text": "✅ Подтвердить", "callback_data": f"ok:{doc_id}"}],
                [{"text": "✏️ Исправить", "callback_data": f"edit:{doc_id}"}]
            ]}
            
            print(f"📤 [WORKER] Этап 5: Отправка сообщения пользователю...")
            send_message(chat_id, msg, reply_markup=kb)
            print(f"🏁 [WORKER] Задача #{doc_id} полностью обработана!")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"❌ [WORKER] КРИТИЧЕСКАЯ ОШИБКА: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
