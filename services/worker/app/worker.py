import os, json, time, redis, requests
from app.db import init_db, insert_received, update_ocr, get_doc, set_confirmed, set_bitrix_result
from app.ocr import extract_batch
from app.formatting import format_for_driver
from app.telegram_client import download_photo as tg_download, send_message as tg_send
from app.max_client import download_photo as max_download, send_message as max_send, HEADERS as MAX_HEADERS, MAX_API_URL
from app.bitrix_client import send_to_bitrix_sync

def main():
    init_db()
    rds = redis.Redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    print("✅ Worker started. Dual mode + Bitrix Upload active.", flush=True)
    
    while True:
        try:
            item = rds.blpop("tasks", timeout=10)
            if not item: continue
            
            task = json.loads(item[1])
            task_type = task.get("type", "batch")
            platform = task.get("platform", "telegram")
            chat_id = task.get("chat_id")

            # --- ЭТАП ВЫГРУЗКИ В БИТРИКС ---
            if task_type == "bitrix_export":
                doc_id = task["doc_id"]
                mid = task.get("mid")
                print(f"🚀 [WORKER] Выгрузка в Битрикс документа #{doc_id}", flush=True)
                
                doc = get_doc(doc_id)
                if not doc: continue

                ocr = doc.get("ocr_data") or {}
                msg_text = format_for_driver(doc_id, ocr, True, "", 1.0)
                raw_paths = doc.get("photo_path")
                photo_paths = raw_paths.split(",") if raw_paths else []

                ok, resp, err, payload = send_to_bitrix_sync(text=msg_text, photo_paths=photo_paths)

                if ok:
                    set_confirmed(doc_id)
                    set_bitrix_result(doc_id, str(resp.get("result", "")), "success")
                    final_text = "✅ **Успешно отправлено в Битрикс24**\n\n" + msg_text
                else:
                    final_text = "❌ Ошибка отправки: " + str(err) + "\n\n" + msg_text

                if platform == "max" and mid:
                    requests.put(f"{MAX_API_URL}/messages", params={"message_id": mid}, json={"text": final_text}, headers=MAX_HEADERS)
                elif platform == "max": max_send(chat_id, final_text)
                else: tg_send(chat_id, final_text)
                continue

            # --- ЭТАП РАСПОЗНАВАНИЯ ФОТО (OCR) ---
            files = task.get("files", [])
            if not files: continue

            print("📥 [WORKER] Скачивание файлов...", flush=True)
            if platform == "max": paths = [max_download(fid) for fid in files]
            else: paths = [tg_download(fid) for fid in files]
            
            print("🤖 [WORKER] Распознавание...", flush=True)
            data = extract_batch(paths)
            
            # ВАЖНОЕ ИЗМЕНЕНИЕ: Принудительно очищаем перевозчика!
            # Водитель ОБЯЗАН ввести его сам.
            if "carrier_name" in data:
                data["carrier_name"]["value"] = None
            else:
                data["carrier_name"] = {"value": None}
            
            doc_id = insert_received(chat_id, ",".join(files), ",".join(paths))
            update_ocr(doc_id, data, json.dumps(data), data.get("confidence", 0), "ocr_ok", "")
            
            # Поскольку мы очистили поле, здесь format_for_driver покажет прочерк
            msg = format_for_driver(doc_id, data, True, "", data.get("confidence", 0))
            
            # И кнопка "Ввести перевозчика" появится автоматически (так как значение пустое)
            kb = {"inline_keyboard": [
                [{"text": "🚚 Ввести перевозчика", "callback_data": f"field:{doc_id}:carrier_name"}],
                [{"text": "✅ Подтвердить", "callback_data": f"ok:{doc_id}"}],
                [{"text": "✏️ Исправить", "callback_data": f"edit:{doc_id}"}]
            ]}
            
            if platform == "max": max_send(chat_id, msg, reply_markup=kb)
            else: tg_send(chat_id, msg, reply_markup=kb)
            
        except Exception as e:
            print(f"❌ [WORKER] ОШИБКА: {e}", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()
