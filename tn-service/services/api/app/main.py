from fastapi import FastAPI
import json, redis, os, requests, threading, time
from app.db import get_doc, update_field
from app.formatting import format_for_driver

app = FastAPI(title="TN Service Polling")
rds = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

MAX_API_URL = "https://platform-api.max.ru"
MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
HEADERS = {"Authorization": f"{MAX_TOKEN}"}
EDIT_STATE = {}

# === БУФЕР ДЛЯ СКЛЕЙКИ ФАЙЛОВ ===
FILE_BUFFER = {}
BUFFER_LOCK = threading.Lock()

def flush_buffer(chat_id):
    """Отправляет накопленные файлы одной пачкой в Worker"""
    with BUFFER_LOCK:
        if chat_id not in FILE_BUFFER: return
        data = FILE_BUFFER.pop(chat_id)
    
    files = data["files"]
    if not files: return
    
    print(f"📦 Буфер сброшен. Отправляем {len(files)} файлов в обработку.", flush=True)
    rds.rpush("tasks", json.dumps({"type": "batch", "platform": "max", "chat_id": str(chat_id), "files": files}))
    send_max_message(chat_id, f"📥 Принято файлов: {len(files)}. Начинаю распознавание...")

def add_to_buffer(chat_id, new_urls):
    """Добавляет файлы в буфер и перезапускает таймер"""
    with BUFFER_LOCK:
        if chat_id in FILE_BUFFER:
            # Если таймер уже тикает - отменяем его (продлеваем ожидание)
            if FILE_BUFFER[chat_id].get("timer"):
                FILE_BUFFER[chat_id]["timer"].cancel()
            FILE_BUFFER[chat_id]["files"].extend(new_urls)
        else:
            FILE_BUFFER[chat_id] = {"files": new_urls}
        
        # Запускаем таймер на 2.5 секунды
        t = threading.Timer(2.5, flush_buffer, args=[chat_id])
        FILE_BUFFER[chat_id]["timer"] = t
        t.start()
        print(f"⏳ Файл получен. В буфере: {len(FILE_BUFFER[chat_id]['files'])}. Ждем 2.5 сек...", flush=True)

def convert_kb(reply_markup):
    if not reply_markup or "inline_keyboard" not in reply_markup: return None
    max_buttons = []
    for row in reply_markup["inline_keyboard"]:
        max_row = []
        for btn in row:
            max_row.append({"type": "callback", "text": str(btn["text"]), "payload": str(btn.get("callback_data", btn.get("payload", "")))})
        max_buttons.append(max_row)
    return [{"type": "inline_keyboard", "payload": {"buttons": max_buttons}}]

def send_max_message(chat_id, text, reply_markup=None):
    body = {"text": text}
    atts = convert_kb(reply_markup)
    if atts: body["attachments"] = atts
    try:
        resp = requests.post(f"{MAX_API_URL}/messages", params={"chat_id": chat_id}, json=body, headers=HEADERS, timeout=20)
        if resp.status_code == 200: return resp.json().get("message", {}).get("body", {}).get("mid")
    except: pass
    return None

def edit_max_message(mid, text, reply_markup=None):
    if not mid: return
    body = {"text": text}
    atts = convert_kb(reply_markup)
    body["attachments"] = atts if atts else []
    try: requests.put(f"{MAX_API_URL}/messages", params={"message_id": mid}, json=body, headers=HEADERS, timeout=20)
    except: pass

def delete_max_message(mid):
    if not mid: return
    try: requests.delete(f"{MAX_API_URL}/messages", params={"message_id": mid}, headers=HEADERS, timeout=10)
    except: pass

def answer_max_callback(callback_id, notification_text=None):
    if not callback_id or not notification_text: return
    try: requests.post(f"{MAX_API_URL}/answers", params={"callback_id": callback_id}, json={"notification": notification_text}, headers=HEADERS, timeout=5)
    except: pass

def build_main_kb(doc_id, missing_carrier):
    kb = []
    if missing_carrier: kb.append([{"text": "🚚 Ввести перевозчика", "callback_data": f"field:{doc_id}:carrier_name"}])
    kb.append([{"text": "✅ Подтвердить", "callback_data": f"ok:{doc_id}"}])
    kb.append([{"text": "✏️ Исправить", "callback_data": f"edit:{doc_id}"}])
    kb.append([{"text": "📸 Переснять", "callback_data": f"reshoot:{doc_id}"}])
    return {"inline_keyboard": kb}

def build_edit_kb(doc_id):
    return {"inline_keyboard": [
        [{"text": "Наименование перевозчика", "callback_data": f"field:{doc_id}:carrier_name"}],
        [{"text": "Грузоотправитель", "callback_data": f"field:{doc_id}:sender_address"}],
        [{"text": "Дата погрузки", "callback_data": f"field:{doc_id}:loading_date"}],
        [{"text": "ФИО водителя", "callback_data": f"field:{doc_id}:driver_name"}],
        [{"text": "Вес (кг)", "callback_data": f"field:{doc_id}:weight_kg"}],
        [{"text": "Вид продукции", "callback_data": f"field:{doc_id}:product_type"}],
        [{"text": "⬅️ Назад", "callback_data": f"back:{doc_id}"}]
    ]}

def handle_callback(chat_id, data, callback_id, mid):
    if data.startswith("edit:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        if doc:
            ocr = doc.get("ocr_data") or {}
            edit_max_message(mid, f"🛠 **Режим редактирования**\n\n{format_for_driver(doc_id, ocr, True, '', 1.0)}", reply_markup=build_edit_kb(doc_id))
        
    elif data.startswith("field:"):
        _, did, field = data.split(":")
        EDIT_STATE[chat_id] = {"doc_id": int(did), "field": field, "original_mid": mid, "prompt_mid": send_max_message(chat_id, "🚚 Введите Перевозчика:" if field == "carrier_name" else "✍️ Введите новое значение:")}
        
    elif data.startswith("back:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        if doc:
            ocr = doc.get("ocr_data") or {}
            miss = not ocr.get("carrier_name", {}).get("value") or ocr.get("carrier_name", {}).get("value") == "—"
            edit_max_message(mid, format_for_driver(doc_id, ocr, True, '', 1.0), reply_markup=build_main_kb(doc_id, miss))
            
    elif data.startswith("ok:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        if not doc: return
        ocr = doc.get("ocr_data") or {}
        carrier = ocr.get("carrier_name", {}).get("value")
        
        if not carrier or carrier in ("—", "", None):
            current_text = format_for_driver(doc_id, ocr, True, "", 1.0)
            error_text = "⛔ **ОШИБКА: Введите перевозчика!**\nНажмите кнопку «🚚 Ввести перевозчика» ниже.\n\n" + current_text
            edit_max_message(mid, error_text, reply_markup=build_main_kb(doc_id, True))
            return
            
        edit_max_message(mid, "🚀 Отправляю в Битрикс24 вместе с фото...")
        rds.rpush("tasks", json.dumps({"type": "bitrix_export", "platform": "max", "chat_id": str(chat_id), "doc_id": doc_id, "mid": mid}))

def process_update(update):
    update_type = update.get("update_type")
    if update_type == "message_callback":
        cb = update.get("callback", {})
        chat_id = update.get("message", {}).get("recipient", {}).get("chat_id")
        if chat_id and cb.get("payload"): threading.Thread(target=handle_callback, args=(chat_id, cb.get("payload"), cb.get("callback_id"), update.get("message", {}).get("body", {}).get("mid"))).start()
        return

    if update_type not in ["message_created", "bot_started"]: return
    msg_obj = update.get("message", {})
    chat_id = msg_obj.get("recipient", {}).get("chat_id") or update.get("chat_id")
    text = msg_obj.get("body", {}).get("text", "")
    attachments = msg_obj.get("body", {}).get("attachments", [])

    if not chat_id: return

    state = EDIT_STATE.pop(chat_id, None)
    if state and text and update_type != "bot_started":
        doc_id, field = state["doc_id"], state["field"]
        update_field(doc_id, field, text.strip())
        doc = get_doc(doc_id)
        ocr = doc.get("ocr_data") or {}
        msg_text = format_for_driver(doc_id, ocr, True, "", 1.0)
        miss = not ocr.get("carrier_name", {}).get("value")
        
        if state.get("original_mid"): edit_max_message(state["original_mid"], msg_text, reply_markup=build_main_kb(doc_id, miss))
        delete_max_message(state.get("prompt_mid"))
        delete_max_message(msg_obj.get("body", {}).get("mid"))
        return

    if update_type == "bot_started" or text.lower() == "старт":
        send_max_message(chat_id, "👋 Привет! Я бот Альфамонолит.\nПришлите фото накладной для распознавания.")
        return

    # СОБИРАЕМ И ФОТО, И ФАЙЛЫ
    urls = [
        a.get("payload", {}).get("url") 
        for a in attachments 
        if (a.get("type") == "image" or a.get("type") == "file") and a.get("payload", {}).get("url")
    ]
    
    # ЕСЛИ ЕСТЬ ФАЙЛЫ - КЛАДЕМ В БУФЕР, А НЕ ОТПРАВЛЯЕМ СРАЗУ
    if urls:
        add_to_buffer(chat_id, urls)

def polling_loop():
    marker = None
    while True:
        try:
            resp = requests.get(f"{MAX_API_URL}/updates", headers=HEADERS, params={"marker": marker} if marker else {}, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                if "marker" in data: marker = data["marker"]
                for u in data.get("updates", []): process_update(u)
            else: time.sleep(2)
        except Exception: time.sleep(5)

@app.on_event("startup")
def startup_event(): threading.Thread(target=polling_loop, daemon=True).start()
