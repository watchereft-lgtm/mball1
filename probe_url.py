"""Проверка ссылки в QR-коде через живой сервер: присылаем адрес так, как это делает браузер.

Запуск (сервер должен быть уже запущен):

    python probe_url.py              # порт 8501
    python probe_url.py 8600         # другой порт

Что проверяется: приложение берёт адрес из запроса, а не из зашитой строки. Поэтому
один и тот же код даёт правильный QR и в облаке, и на localhost, и в локальной сети.
"""
from __future__ import annotations

import asyncio
import re
import sys

import websockets
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

CASES = (
    "https://magic-ball.streamlit.app",
    "http://localhost:8501",
    "http://192.168.43.225:8501",
)

failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    print(("  OK   " if condition else "  FAIL ") + label + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def back_message(url: str) -> bytes:
    message = BackMsg()
    message.rerun_script.query_string = ""
    message.rerun_script.page_script_hash = ""
    message.rerun_script.context_info.url = url
    message.rerun_script.context_info.timezone = "Europe/Moscow"
    message.rerun_script.context_info.locale = "ru-RU"
    message.rerun_script.context_info.color_scheme = "light"
    return message.SerializeToString()


async def qr_link(port: str, url: str) -> str:
    async with websockets.connect(f"ws://127.0.0.1:{port}/_stcore/stream", max_size=None) as socket:
        await socket.send(back_message(url))
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=30)
            forward = ForwardMsg()
            forward.ParseFromString(raw)
            kind = forward.WhichOneof("type")
            if kind == "delta" and forward.delta.new_element.HasField("markdown"):
                body = forward.delta.new_element.markdown.body
                found = re.search(r"http[s]?://[^\s`\"<]+screen=game", body)
                if found:
                    return found.group(0)
            if kind == "script_finished":
                return ""


async def main(port: str) -> int:
    print(f"Ссылка в QR-коде (сервер на порту {port})")
    for opened in CASES:
        try:
            link = await qr_link(port, opened)
        except Exception as exc:
            check(False, f"браузер открыл {opened}", f"{type(exc).__name__}: {exc}")
            continue
        expected = opened.rstrip("/") + "/?screen=game"
        check(link == expected, f"браузер открыл {opened}", f"QR ведёт на {link or 'ничего'}")

    if failures:
        print(f"\nИТОГ: провалено — {len(failures)}: {failures}")
        return 1
    print("\nИТОГ: адрес берётся из запроса, зашитых адресов нет")
    return 0


if __name__ == "__main__":
    port_argument = sys.argv[1] if len(sys.argv) > 1 else "8501"
    raise SystemExit(asyncio.run(main(port_argument)))
