"""本地通知验收接收器；仅 Compose 内部及宿主回环访问，禁止用作公网收件器。"""

from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

events = deque(maxlen=1000)
log = Path("/data/events.jsonl")
log.parent.mkdir(parents=True, exist_ok=True)
if log.exists():
    # 仅恢复最近事件，历史日志保存在本地 Docker volume。
    with log.open(encoding="utf-8") as source:
        for line in source:
            events.append(json.loads(line))


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/events":
            self.reply(200, list(events))
        elif self.path == "/health":
            self.reply(200, {"status": "ok"})
        else:
            self.reply(404, {})

    def do_POST(self):
        if self.path != "/alerts":
            self.reply(404, {})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1048576:
                self.reply(413, {})
                return
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
                raise ValueError("invalid webhook")
        except (ValueError, UnicodeError):
            self.reply(400, {})
            return
        event = {"received_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        # 先持久化，后确认接收，避免未落盘就应答成功。
        with log.open("a", encoding="utf-8") as target:
            target.write(json.dumps(event, ensure_ascii=False) + "\n")
        events.append(event)
        self.reply(200, {"accepted": True})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
