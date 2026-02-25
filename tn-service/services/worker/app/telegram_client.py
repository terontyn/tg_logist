import os
import time
import requests
from PIL import Image

from .config import API_BASE, FILE_BASE, DOWNLOAD_DIR

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def send_message(chat_id, text, reply_markup=None, attempts=3):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    last_err = None
    for i in range(1, attempts + 1):
        try:
            resp = requests.post(
                f"{API_BASE}/sendMessage",
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram ok=false: {data}")
            return True
        except Exception as e:
            last_err = e
            time.sleep(1.5)

    raise RuntimeError(f"TG sendMessage failed after {attempts} attempts: {last_err}")


def get_file_path(file_id):
    resp = requests.get(
        f"{API_BASE}/getFile",
        params={"file_id": file_id},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getFile ok=false: {data}")
    return data["result"]["file_path"]


def download_photo(file_id):
    path = get_file_path(file_id)
    url = f"{FILE_BASE}/{path}"
    
    # Путь для финального JPEG и путь для временного сырого файла из Телеграма
    local = f"{DOWNLOAD_DIR}/{file_id}.jpg"
    tmp_local = f"{DOWNLOAD_DIR}/{file_id}_tmp.file"

    # Скачиваем во временный файл
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp_local, "wb") as f:
            for chunk in r.iter_content(1024 * 128):
                if chunk:
                    f.write(chunk)

    # Безопасная конвертация из WebP (или чего угодно) в настоящий JPEG
    try:
        with Image.open(tmp_local) as img:
            rgb_im = img.convert("RGB")
            rgb_im.save(local, "JPEG", quality=95)
        os.remove(tmp_local)  # Удаляем временный файл, оставляем только чистый JPEG
    except Exception as e:
        print(f"⚠️ Ошибка конвертации {local}: {e}")
        # На крайний случай, если файл не картинка, просто переименовываем
        os.rename(tmp_local, local)

    return local
