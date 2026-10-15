"""Магический шар предсказаний — веб-приложение на Streamlit.

Две роли на одном адресе:
  /                — витрина для аудитории: название и большой QR-код
  /?screen=game    — игра, которую открывает телефон (именно эта ссылка в QR)

Работает и в облаке (Streamlit Community Cloud), и локально: ссылку для QR
приложение берёт из адреса, по которому его открыли, поэтому зашитых адресов нет.

Ничего не сохраняется на диск: вся история живёт в session_state вкладки.
"""
from __future__ import annotations

import io
import json
import os
import random
import socket
import sys
from base64 import b64encode
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st
from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

APP_DIR = Path(__file__).resolve().parent
POOLS_FILE = APP_DIR / "pools.json"
CATEGORIES = ("yes", "no", "later", "vague")
CATEGORY_TITLES = {
    "yes": "Да",
    "no": "Нет",
    "later": "Позже",
    "vague": "Туманно",
}
RECENT_LIMIT = 3

PRESET_QUESTIONS = [
    "Сдам ли я контрольную?",
    "Вызовут ли меня к доске?",
    "Позовут ли меня гулять?",
    "Получу ли я пятёрку?",
    "Зададут ли много домашки?",
    "Помирюсь ли я с другом?",
    "Будет ли сегодня хороший день?",
    "Стоит ли мне начать готовиться сейчас?",
    "Повезёт ли мне с вариантом?",
    "Найду ли я свою сменку?",
]

st.set_page_config(
    page_title="Магический шар",
    page_icon="🔮",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={},
)


# ----------------------------------------------------------------------------- данные

def load_pools(path: Path) -> tuple[dict, list[str]]:
    """Читает pools.json. Возвращает (пулы, список предупреждений)."""
    warnings: list[str] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(f"Файл {path.name} не найден — играю классическим набором.")
        return {}, warnings
    except json.JSONDecodeError as exc:
        warnings.append(f"{path.name} не разобран ({exc.lineno}:{exc.colno}) — играю классическим набором.")
        return {}, warnings

    pools: dict[str, dict] = {}
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        phrases = [str(p).strip() for p in value.get("phrases", []) if str(p).strip()]
        if not phrases:
            warnings.append(f"Набор «{key}» пропущен: в нём нет фраз.")
            continue
        category = str(value.get("category", "vague")).lower().strip()
        if category not in CATEGORIES:
            warnings.append(f"Набор «{key}»: категория «{category}» неизвестна, считаю её «vague».")
            category = "vague"
        pools[key] = {
            "title": str(value.get("title", key)),
            "enabled": bool(value.get("enabled", False)),
            "category": category,
            "phrases": phrases,
        }

    if not pools:
        warnings.append("В pools.json нет ни одного набора — играю классическим набором.")
    return pools, warnings


def enabled_by_category(pools: dict) -> dict[str, list[str]]:
    """Фразы включённых наборов, разложенные по категориям."""
    result: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for pool in pools.values():
        if pool["enabled"]:
            result[pool["category"]].extend(pool["phrases"])
    if not any(result.values()) and "classic" in pools:
        result[pools["classic"]["category"]].extend(pools["classic"]["phrases"])
    return result


def draw_answer(by_category: dict[str, list[str]], state) -> str | None:
    """Сначала тянет категорию (не ту, что была только что), потом фразу (не из последних трёх)."""
    categories = [c for c in CATEGORIES if by_category.get(c)]
    if not categories:
        return None
    fresh = [c for c in categories if c != state.get("last_category")] or categories
    category = random.choice(fresh)
    pool = list(dict.fromkeys(by_category[category]))
    recent = set(state.get("recent", []))
    candidates = [p for p in pool if p not in recent]
    if not candidates:
        candidates = pool
    phrase = random.choice(candidates)
    state["last_category"] = category
    state["recent"] = ([phrase] + [p for p in state.get("recent", []) if p != phrase])[:RECENT_LIMIT]
    return phrase


# ----------------------------------------------------------------------------- вспомогательное

def is_lan_address(value: str) -> bool:
    """Приватный адрес локальной сети — то, что вообще может открыть телефон."""
    if value.startswith(("127.", "169.254.")):
        return False
    octets = value.split(".")
    if len(octets) != 4:
        return False
    try:
        first, second = int(octets[0]), int(octets[1])
    except ValueError:
        return False
    return (
        first == 10
        or (first == 172 and 16 <= second <= 31)
        or (first == 192 and second == 168)
    )


def local_ip() -> str:
    """IPv4, по которому телефон дотянется до этой машины."""
    # 1) адрес, выбранный при запуске run.ps1 — он же напечатан в консоли
    try:
        chosen = (APP_DIR / ".ip").read_text(encoding="ascii").strip()
        if is_lan_address(chosen):
            return chosen
    except OSError:
        pass
    # 2) адрес интерфейса, через который машина выходит в сеть
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            candidate = probe.getsockname()[0]
        if is_lan_address(candidate):
            return candidate
    except OSError:
        pass
    # 3) перебор адресов хоста
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidate = info[4][0]
            if is_lan_address(candidate):
                return candidate
    except OSError:
        pass
    return "127.0.0.1"


def qr_data_uri(url: str) -> str | None:
    try:
        import qrcode
        from qrcode.image.pil import PilImage  # noqa: F401  (проверка, что PIL доступен)
    except Exception:
        try:
            import qrcode  # type: ignore
            import qrcode.image.pil  # noqa: F401
        except Exception:
            return None

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + b64encode(buffer.getvalue()).decode("ascii")


def inject_base_css() -> None:
    st.markdown(
        """
        <style>
          #MainMenu, header [data-testid="stStatusWidget"], footer {visibility: hidden;}
          .block-container {padding-top: 1.2rem; padding-bottom: 1.2rem;}
          .mb-title {font-size: 2rem; font-weight: 700; text-align: center; margin: 0 0 1rem 0;}
          .mb-title small {display: block; font-size: 1rem; font-weight: 400; opacity: .6; margin-top: .4rem;}
          .mb-answer {
            font-size: 1.9rem; font-weight: 700; line-height: 1.25;
            text-align: center; padding: 1.4rem 1rem; margin: 0.8rem 0 0.4rem 0;
            border: 2px solid currentColor; border-radius: 1rem;
          }
          .mb-hint {text-align: center; opacity: .65; font-size: .95rem; margin-top: .6rem;}
          /* Витрина: QR не должен упираться в край и обрезаться.
             Раньше ширина считалась через 70vh, а во вложенном контейнере облака
             vh считается от окна целиком — картинка вылезала за экран. */
          .mb-qr {display: flex; justify-content: center; align-items: center; margin: 0;}
          .mb-qr img {
            display: block;
            width: 100%;
            max-width: 520px;
            height: auto;
            image-rendering: pixelated;
            border: 12px solid #fff;
            border-radius: 6px;
            box-sizing: content-box;
          }
          /* Телефоны и планшеты: сенсорный ввод без наведения мышью.
             Проверяем именно это, а не ширину окна: телефон в альбомной
             ориентации шире 640px и под простое правило «до 640px» не попадал. */
          @media (max-width: 900px) and (hover: none), (max-width: 640px) {
            /* Только размеры. Высоту контейнеров не трогаем: попытка разрешить
               прокрутку изнутри приложения сделала хуже, потому что прокруткой
               управляет обёртка снаружи.
               Картинка ограничена через svh — это НАИМЕНЬШАЯ возможная высота
               экрана на телефоне, поэтому витрина помещается целиком даже когда
               адресная строка браузера развёрнута. Обычный vh здесь врёт: он
               считается от максимальной высоты. */
            .block-container {padding-top: 1.4rem !important;}
            .mb-title {font-size: 1.35rem; margin-bottom: .6rem;}
            .mb-qr img {width: auto; max-width: min(72vw, 38svh, 38vh); border-width: 8px;}
            .mb-answer {font-size: 1.45rem; padding: .9rem .6rem;}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------- экраны

def current_port() -> str:
    """Порт сервера: сначала файл от run.ps1, затем заголовок Host."""
    try:
        value = (APP_DIR / ".port").read_text(encoding="ascii").strip()
        if value.isdigit():
            return value
    except OSError:
        pass
    try:
        host = st.context.headers.get("Host", "")
        if ":" in host:
            candidate = host.rsplit(":", 1)[-1]
            if candidate.isdigit():
                return candidate
    except Exception:
        pass
    return "8501"


def context_url() -> str:
    """Адрес, по которому приложение открыл браузер: https://имя.streamlit.app или http://localhost:8501.

    Streamlit отдаёт его в контексте запуска; параметры запроса в него не входят.
    """
    try:
        ctx = get_script_run_ctx()
        info = getattr(ctx, "context_info", None) if ctx is not None else None
        url = getattr(info, "url", None)
        if url:
            return str(url).strip()
    except Exception:
        pass
    return ""


def base_url() -> str:
    """Базовый адрес приложения без параметров запроса.

    Порядок: ручное переопределение -> адрес из браузера -> локальная сеть.
    В облаке второй источник срабатывает сам, поэтому вписывать адрес не нужно.
    """
    override = os.environ.get("MAGIC_BALL_PUBLIC_URL", "").strip()
    if not override:
        try:
            value = st.query_params.get("url", "")
            if isinstance(value, list):
                value = value[0] if value else ""
            override = str(value).strip()
        except Exception:
            override = ""
    if override:
        return override.rstrip("/")

    from_context = context_url()
    if from_context:
        return from_context.rstrip("/")

    return f"http://{local_ip()}:{current_port()}"


def build_url(params: dict[str, str] | None = None) -> str:
    """Собирает ссылку на приложение, добавляя параметры к любому базовому адресу."""
    base = base_url()
    parts = urlsplit(base)
    path = parts.path
    if not path:
        # «https://имя.streamlit.app?screen=game» и «http://localhost:8501?screen=game»
        # выглядят криво: перед параметрами всегда должна быть косая черта
        path = "/"
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in (params or {}).items():
        if value:
            query[key] = value
        else:
            query.pop(key, None)
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ""))


def game_url() -> str:
    """Ссылка для телефона: та же страница, но с включённой игрой."""
    return build_url({"screen": "game"})


def screen_showcase() -> None:
    st.markdown('<div class="mb-title">Магический шар предсказаний</div>', unsafe_allow_html=True)

    url = game_url()
    data_uri = qr_data_uri(url)
    if data_uri is None:
        st.error("Не удалось построить QR-код: библиотека qrcode недоступна.")
        st.code(url, language=None)
    else:
        st.markdown(f'<div class="mb-qr"><img src="{data_uri}" alt="QR-код игры"></div>', unsafe_allow_html=True)

    with st.expander("Служебное"):
        st.write(f"Адрес игры (он же внутри QR): `{url}`")
        st.caption(
            "Ссылка берётся из адреса, по которому открыта эта страница. "
            "Чтобы задать её вручную, добавьте ?url=https://ваш-адрес или переменную окружения MAGIC_BALL_PUBLIC_URL."
        )


def apply_preset() -> None:
    """Выбор из списка переносим в поле вопроса — до создания самого поля."""
    chosen = st.session_state.get("preset", "")
    if chosen:
        st.session_state["question"] = chosen


def ask_ball(by_category: dict[str, list[str]]) -> None:
    answer = draw_answer(by_category, st.session_state)
    if answer is None:
        st.session_state["answer"] = ""
        st.session_state["ask_error"] = True
        return
    st.session_state["ask_error"] = False
    st.session_state["answer"] = answer
    st.session_state["answer_for"] = st.session_state.get("question", "").strip()
    st.session_state["ask_count"] = st.session_state.get("ask_count", 0) + 1


def screen_game() -> None:
    st.markdown('<div class="mb-title" style="font-size:1.5rem">🔮 Магический шар</div>', unsafe_allow_html=True)

    pools, warnings = load_pools(POOLS_FILE)
    by_category = enabled_by_category(pools)

    for message in warnings:
        st.warning(message)

    if not any(by_category.values()):
        st.error("Нет ни одной фразы для предсказаний. Проверьте pools.json.")
        return

    active = [p["title"] for p in pools.values() if p["enabled"]]
    if active:
        st.caption("Активные наборы: " + ", ".join(active))

    st.text_input(
        "Твой вопрос",
        key="question",
        placeholder="Например: сдам ли я контрольную?",
    )

    st.selectbox(
        "Или выбери готовый вопрос",
        options=[""] + PRESET_QUESTIONS,
        key="preset",
        on_change=apply_preset,
        format_func=lambda value: "Выбрать из списка…" if value == "" else value,
    )

    st.button(
        "Спросить ещё" if st.session_state.get("answer") else "Спросить шар",
        type="primary",
        use_container_width=True,
        on_click=ask_ball,
        args=(by_category,),
    )

    if st.session_state.get("ask_error"):
        st.error("Шар не нашёл ни одной фразы. Проверьте pools.json.")

    answer = st.session_state.get("answer")
    if answer:
        st.markdown(f'<div class="mb-answer">{answer}</div>', unsafe_allow_html=True)
        asked = st.session_state.get("answer_for")
        if asked:
            st.markdown(f'<div class="mb-hint">Вопрос: {asked}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="mb-hint">Предсказаний за сеанс: {st.session_state.get("ask_count", 0)}</div>',
            unsafe_allow_html=True,
        )


def render_html(markup: str, height: int | None = None) -> None:
    """Вставляет HTML в саму страницу приложения, а не в отдельный компонент.

    st.html (Streamlit 1.33+) рендерит разметку в основном документе, поэтому
    стили и скрипты видят настоящую страницу. Если версия старая — откатываемся
    на components.html, который рисует в изолированном iframe.
    """
    html_function = getattr(st, "html", None)
    if html_function is not None and height is None:
        html_function(markup)
        return
    import streamlit.components.v1 as components

    components.html(markup, height=height or 300)


def screen_diagnostics() -> None:
    """Отладочный экран /?debug=1: линейка и измерения, без чужих документов.

    Ничего не пытаемся достать из родительской страницы: браузер этого не даёт.
    Вместо этого рисуем линейку прямо в документе приложения — по ней видно
    глазами, сколько экрана видно, — и печатаем размеры окна.
    """
    ticks = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;height:50px;'
        f'border-top:1px solid #bbb;font:14px monospace;">'
        f'<span style="width:64px;text-align:right;">{value}</span>'
        f'<span style="flex:1;height:8px;background:{"#6C4AB6" if value % 200 == 0 else "#ddd"};"></span>'
        f"</div>"
        for value in range(0, 1401, 50)
    )
    render_html(
        '<div id="mb-ruler" style="font:16px/1.5 monospace;">'
        '<div style="padding:8px 0;font-weight:700;">Линейка: числа — пиксели от верха страницы.</div>'
        f"{ticks}"
        '<div style="padding:10px 0;font-weight:700;">'
        "Найдите самое верхнее видимое число: это и есть обрезанная часть."
        "</div>"
        "</div>"
        '<div id="mb-measure" style="font:18px/1.6 monospace;background:#111;color:#0f0;'
        'padding:12px;border-radius:8px;margin-top:12px;">Измеряю…</div>'
        "<script>"
        "(function(){"
        "  function draw(){"
        "    var p = window.parent;"
        "    var lines = [];"
        "    function push(n, v){ lines.push(n + ': ' + v); }"
        "    push('ширина окна', window.innerWidth);"
        "    push('высота окна', window.innerHeight);"
        "    try { push('высота окна снаружи', p.innerHeight); }"
        "    catch (e) { push('высота окна снаружи', 'недоступно'); }"
        "    if (window.visualViewport) {"
        "      push('видимая высота', Math.round(window.visualViewport.height));"
        "      push('сдвиг видимой области', Math.round(window.visualViewport.offsetTop));"
        "    }"
        "    push('высота страницы', document.documentElement.scrollHeight);"
        "    push('прокрутка', Math.round(window.scrollY));"
        "    push('поддержка svh', CSS.supports('height', '100svh') ? 'да' : 'нет');"
        "    document.getElementById('mb-measure').textContent = lines.join('\\n');"
        "  }"
        "  draw(); setTimeout(draw, 900); window.addEventListener('resize', draw);"
        "})();"
        "</script>"
    )


def main() -> None:
    inject_base_css()
    screen = st.query_params.get("screen", "")
    if isinstance(screen, list):
        screen = screen[0] if screen else ""
    debug = st.query_params.get("debug", "")
    if isinstance(debug, list):
        debug = debug[0] if debug else ""
    if debug:
        screen_diagnostics()
    elif screen == "game":
        screen_game()
    else:
        screen_showcase()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # чтобы ошибка была видна и на телефоне
        st.error(f"Ошибка приложения: {exc}")
        print(f"[magic-ball] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
