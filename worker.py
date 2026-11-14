from __future__ import annotations

import json
import logging
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from config import cfg
from pipeline import answer_question, ensure_kb_initialized

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("worker")


class InternalBridgeHandler(BaseHTTPRequestHandler):
    """Легковесный HTTP-обработчик для взаимодействия с Go-бэкендом."""

    server_version = "PSBInternalBridge/1.0"

    def _send_json(self, status: HTTPStatus, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/internal/health" or self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok", "worker": "python-core"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Endpoint not found"})

    def do_POST(self) -> None:
        if self.path == "/internal/answer":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                self._send_json(HTTPStatus.BAD_REQUEST, {"detail": "Empty request body"})
                return

            try:
                body = self.rfile.read(content_length)
                req_data = json.loads(body.decode("utf-8"))
            except Exception as exc:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": f"Invalid JSON: {exc}"})
                return

            question = req_data.get("question", "")
            if not isinstance(question, str):
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": "'question' must be a string"})
                return

            try:
                result = answer_question(question)
                self._send_json(HTTPStatus.OK, result.to_dict())
            except Exception as exc:
                logger.error("Error processing answer: %s", exc, exc_info=True)
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": f"Internal error: {exc}"})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Endpoint not found"})

    def log_message(self, format: str, *args: Any) -> None:
        # Подавление избыточных логов в stderr для чистоты вывода
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


def run_worker(port: int = cfg.WORKER_PORT, host: str = "0.0.0.0") -> None:
    ensure_kb_initialized()
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, InternalBridgeHandler)
    logger.info("Python RAG Core Worker running on http://%s:%d", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    port = cfg.WORKER_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_worker(port=port)
