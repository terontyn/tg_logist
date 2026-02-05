import os
import json
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")
# у тебя бывало: DATABASE_URL="DATABASE_URL=postgresql://..."
if DATABASE_URL.startswith("DATABASE_URL="):
    DATABASE_URL = DATABASE_URL.split("=", 1)[1].strip()


def db_connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def set_status(doc_id: int, status: str):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE transport_documents SET status=%s WHERE id=%s",
                (status, doc_id),
            )
        conn.commit()


def update_field(doc_id: int, field: str, value):
    """
    Обновляем ocr_data JSONB по выбранному полю.
    field: base_name, loading_date, driver_name, weight_kg, product_type
    """
    with db_connect() as conn:
        with conn.cursor() as cur:
            # Получаем текущий JSON
            cur.execute("SELECT ocr_data FROM transport_documents WHERE id=%s", (doc_id,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError("doc not found")
            data = row["ocr_data"] or {}

            if field == "base_name":
                data.setdefault("loading_base", {})
                data["loading_base"]["name"] = value
            elif field == "loading_date":
                data.setdefault("loading_date", {})
                data["loading_date"]["value"] = value
            elif field == "driver_name":
                data.setdefault("driver_name", {})
                data["driver_name"]["value"] = value
            elif field == "product_type":
                data.setdefault("product_type", {})
                data["product_type"]["value"] = value
            elif field == "weight_kg":
                data.setdefault("weight_total", {})
                data["weight_total"]["kg"] = int(str(value).replace(" ", ""))
                # пересчёт тонн
                data["weight_total"]["value"] = round(data["weight_total"]["kg"] / 1000.0, 3)
                data["weight_total"]["unit"] = "t"
            else:
                raise RuntimeError("unknown field")

            cur.execute(
                "UPDATE transport_documents SET ocr_data=%s WHERE id=%s",
                (json.dumps(data, ensure_ascii=False), doc_id),
            )
        conn.commit()


def get_doc(doc_id: int):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, ocr_data FROM transport_documents WHERE id=%s",
                (doc_id,),
            )
            row = cur.fetchone()
            return row
