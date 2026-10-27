"""Offline adapter: real document formatter, synthetic OCR fixture, local JSON state.
No Telegram, MAX, Redis, PostgreSQL, OCR API or Bitrix requests are made.
"""
import argparse
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("document_formatting", HERE.parent / "tn-service/services/api/app/formatting.py")
formatting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formatting)
lock = Lock()

def save_document(data, path):
    # Replacing a local file keeps reload state without writing production data.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, content, kind="application/json; charset=utf-8"):
        raw = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/":
            return self.reply(200, (HERE / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if self.path == "/api/document":
            with lock:
                data = json.loads(self.server.state_file.read_text(encoding="utf-8"))
            return self.reply(200, json.dumps({"data": data, "formatted": formatting.format_for_driver(1, data, True, "", 1.0)}, ensure_ascii=False))
        self.reply(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/api/document":
            return self.reply(404, '{"error":"not found"}')
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 16384:
                return self.reply(413, '{"error":"request too large"}')
            body = json.loads(self.rfile.read(size))
            carrier, address = (str(body.get(k, "")).strip() for k in ("carrier", "address"))
            if not carrier or not address or max(len(carrier), len(address)) > 500:
                return self.reply(400, '{"error":"Заполните перевозчика и выгрузку, до 500 символов"}')
            operation = body.get("operation", "loading")
            if operation not in ("loading", "unloading"):
                return self.reply(400, '{"error":"unknown operation"}')
            with lock:
                data = json.loads(self.server.state_file.read_text(encoding="utf-8"))
                data["carrier_name"] = {"value": carrier}
                data["unloading_address"] = {"value": address}
                data["operation_events"] = [{"type": operation, "date": "27.10.2026"}]
                save_document(data, self.server.state_file)
            self.reply(200, '{"saved":true,"external_requests":0}')
        except (ValueError, TypeError):
            self.reply(400, '{"error":"invalid JSON"}')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8761)
    parser.add_argument("--state", type=Path, default=HERE / ".state.json")
    args = parser.parse_args()
    if not args.state.exists():
        save_document(json.loads((HERE / "fixture.json").read_text(encoding="utf-8")), args.state)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state_file = args.state
    print(f"Offline demo: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
