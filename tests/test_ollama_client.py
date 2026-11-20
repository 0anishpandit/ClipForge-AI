import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from clipforge.ai.ollama import OllamaClient
from clipforge.errors import OllamaError


def make_server(chat_status=200, chat_body=None, tags=None):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, obj):
            body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200, {"models": [{"name": n} for n in (tags or [])]})

        def do_POST(self):
            seen["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(chat_status, chat_body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen, f"http://127.0.0.1:{server.server_port}"


def reply(content):
    return {"message": {"content": content}}


def test_list_models():
    server, _, url = make_server(tags=["qwen2.5:3b", "llama3"])
    try:
        assert OllamaClient(url, "x").list_models() == ["qwen2.5:3b", "llama3"]
    finally:
        server.shutdown()


def test_list_models_unreachable():
    assert OllamaClient("http://127.0.0.1:1", "x").list_models() is None


def test_chat_json_success_and_payload():
    good = {"clips": [{"title": "t"}]}
    server, seen, url = make_server(chat_body=reply(json.dumps(good)))
    try:
        client = OllamaClient(url + "/", "my-model", num_ctx=4096, max_tokens=123)
        assert client.chat_json("sys", "user") == good
    finally:
        server.shutdown()
    p = seen["payload"]
    assert p["model"] == "my-model" and p["format"] == "json" and p["stream"] is False
    assert p["options"]["num_ctx"] == 4096 and p["options"]["num_predict"] == 123
    assert [m["role"] for m in p["messages"]] == ["system", "user"]


@pytest.mark.parametrize("body,match", [
    (reply(""), "empty"),
    (reply("not json"), "invalid JSON"),
    (reply('{"other": 1}'), "clips list"),
    (reply('["a"]'), "clips list"),
])
def test_chat_json_bad_replies(body, match):
    server, _, url = make_server(chat_body=body)
    try:
        with pytest.raises(OllamaError, match=match):
            OllamaClient(url, "m").chat_json("s", "u")
    finally:
        server.shutdown()


def test_chat_json_http_error():
    server, _, url = make_server(chat_status=500, chat_body={"error": "model not found"})
    try:
        with pytest.raises(OllamaError, match="500.*model not found"):
            OllamaClient(url, "m").chat_json("s", "u")
    finally:
        server.shutdown()


def test_chat_json_connection_refused():
    with pytest.raises(OllamaError, match="connect"):
        OllamaClient("http://127.0.0.1:1", "m", timeout=2).chat_json("s", "u")
