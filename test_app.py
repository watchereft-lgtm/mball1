"""Проверка приложения без браузера: AppTest прогоняет app.py как Streamlit."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / ".pylibs"))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str((APP_DIR / "app.py").resolve())
TMP = APP_DIR / ".testtmp"
TMP.mkdir(exist_ok=True)
os.environ["TMP"] = str(TMP)
os.environ["TEMP"] = str(TMP)
failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    print(("  OK   " if condition else "  FAIL ") + label + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        failures.append(label)


print("1) Витрина (по умолчанию)")
at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "витрина запускается без исключений", str(at.exception))
md = "\n".join(block.value for block in at.markdown)
check("Магический шар предсказаний" in md, "на витрине есть название")
check("data:image/png;base64," in md, "на витрине есть QR-код картинкой")
check("mb-qr" in md, "QR вставлен крупным блоком")

print("2) Игра (?screen=game)")
at2 = AppTest.from_file(APP, default_timeout=60)
at2.query_params["screen"] = "game"
at2.run()
check(not at2.exception, "игра запускается без исключений", str(at2.exception))
check(len(at2.text_input) == 1, "есть поле вопроса")
check(len(at2.selectbox) == 1, "есть список готовых вопросов")
check(len(at2.button) == 1, "есть кнопка вопроса")
check(len(at2.selectbox[0].options) >= 11, "готовых вопросов не меньше десяти")

print("3) Ответ на вопрос")
at2.text_input[0].set_value("Сдам ли я контрольную?").run()
at2.button[0].click().run()
check(not at2.exception, "кнопка не ломает приложение", str(at2.exception))
answer = at2.session_state.get("answer")
check(isinstance(answer, str) and len(answer) > 3, "шар выдал осмысленное предсказание", repr(answer))
check(at2.session_state.get("answer_for") == "Сдам ли я контрольную?", "вопрос сохранился рядом с ответом")
md2 = "\n".join(block.value for block in at2.markdown)
check("mb-answer" in md2, "ответ показан крупным блоком")
check(str(answer) in md2, "текст ответа есть на странице")

print("4) Повторы и счётчик")
answers = [answer]
for _ in range(6):
    at2.button[0].click().run()
    answers.append(at2.session_state.get("answer"))
check(at2.session_state.get("ask_count") == 7, "счётчик предсказаний растёт", str(at2.session_state.get("ask_count")))
check(len(set(answers)) >= 5, "предсказания не повторяются подряд", str(answers))
no_adjacent = all(answers[i] != answers[i + 1] for i in range(len(answers) - 1))
check(no_adjacent, "одна и та же фраза не выпадает дважды подряд", str(answers))

print("5) Готовый вопрос из списка")
at2.selectbox[0].set_value("Позовут ли меня гулять?").run()
check(at2.session_state.get("question") == "Позовут ли меня гулять?", "выбор из списка подставился в поле")

print("6) Переключение наборов в pools.json")
import json  # noqa: E402

pools = json.loads((APP_DIR / "pools.json").read_text(encoding="utf-8"))
enabled_titles = [v["title"] for k, v in pools.items() if not k.startswith("_") and v.get("enabled")]
check(pools["scary"]["enabled"] is False, "страшилки по умолчанию выключены")
check("Страшилки" not in enabled_titles, "выключенный набор не попадает в активные")
check(pools["school_life"]["enabled"] is True, "школьный набор включён")

print("7) Ссылка внутри QR — облако, локальная сеть и переопределения")
import app  # noqa: E402

os.environ.pop("MAGIC_BALL_PUBLIC_URL", None)

# 7.1. Адрес из браузера (так это работает в облаке).
app.context_url = lambda: "https://magic-ball.streamlit.app"
os.environ["MAGIC_BALL_PUBLIC_URL"] = ""
check(
    app.game_url() == "https://magic-ball.streamlit.app/?screen=game",
    "в облаке QR ведёт на публичный адрес",
    app.game_url(),
)
check(
    app.build_url() == "https://magic-ball.streamlit.app/",
    "у адреса появляется завершающая косая черта",
    app.build_url(),
)
check(
    app.base_url() == "https://magic-ball.streamlit.app",
    "базовый адрес хранится без косой черты и параметров",
    app.base_url(),
)

# 7.2. Ручное переопределение через переменную окружения.
os.environ["MAGIC_BALL_PUBLIC_URL"] = "https://ball.example.org/magic"
check(
    app.game_url() == "https://ball.example.org/magic?screen=game",
    "переменная окружения переопределяет адрес",
    app.game_url(),
)
check(
    app.build_url({"theme": "dark"}) == "https://ball.example.org/magic?theme=dark",
    "дополнительные параметры добавляются к адресу",
    app.build_url({"theme": "dark"}),
)
os.environ.pop("MAGIC_BALL_PUBLIC_URL", None)

# 7.3. Локальный запуск: адреса из браузера нет, берём локальную сеть.
app.context_url = lambda: ""
host = app.local_ip()
check(
    app.game_url() == f"http://{host}:{app.current_port()}/?screen=game",
    "локально ссылка собирается из локального адреса",
    app.game_url(),
)
check("streamlit.app" not in app.game_url(), "локальная ссылка не содержит облачного домена")

print()
if failures:
    print(f"ИТОГ: провалено проверок — {len(failures)}: {failures}")
    raise SystemExit(1)
print("ИТОГ: все проверки пройдены")
