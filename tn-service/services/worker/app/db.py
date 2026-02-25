import json
import psycopg
from psycopg.rows import dict_row
from .config import DATABASE_URL

def connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS transport_documents (
          id BIGSERIAL PRIMARY KEY,
          telegram_chat_id BIGINT,
          telegram_file_id TEXT,
          photo_path TEXT,
          ocr_data JSONB,
          ocr_raw TEXT,
          confidence FLOAT,
          status TEXT,
          error_reason TEXT,
          created_at TIMESTAMP DEFAULT now(),
          updated_at TIMESTAMP DEFAULT now()
        );
        """)
        conn.commit()

def insert_received(chat_id, file_id, photo_path):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO transport_documents (telegram_chat_id, telegram_file_id, photo_path, status) VALUES (%s,%s,%s,'received') RETURNING id",
            (chat_id, file_id, photo_path),
        )
        doc_id = cur.fetchone()["id"]
        conn.commit()
        return doc_id

def update_ocr(doc_id, data, raw, conf, status, reason):
    with connect() as conn:
        conn.execute(
            """
            UPDATE transport_documents
            SET ocr_data=%s::jsonb, ocr_raw=%s, confidence=%s, status=%s, error_reason=%s, updated_at=now()
            WHERE id=%s
            """,
            (json.dumps(data, ensure_ascii=False), raw, conf, status, reason, doc_id),
        )
        conn.commit()
