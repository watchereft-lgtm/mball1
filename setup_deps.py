"""Скачивает зависимости с PyPI и распаковывает их в .pylibs — без pip.

Зачем: pip в некоторых изолированных средах не может писать в свои временные папки
(Windows ACL), а здесь нужен только urllib и zipfile из стандартной библиотеки.

    python setup_deps.py            # скачать всё, что нужно приложению
    python setup_deps.py --clean    # сначала удалить .pylibs, затем скачать заново
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import sysconfig
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    from pip._vendor.packaging.markers import Marker
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.utils import canonicalize_name
    from pip._vendor.packaging.version import InvalidVersion, Version
except ImportError:  # если запускают интерпретатором без pip
    try:
        from packaging.markers import Marker  # type: ignore
        from packaging.requirements import Requirement  # type: ignore
        from packaging.specifiers import SpecifierSet  # type: ignore
        from packaging.utils import canonicalize_name  # type: ignore
        from packaging.version import InvalidVersion, Version  # type: ignore
    except ImportError:
        print("Нужен модуль packaging (он входит в pip). Запустите: python -m pip install packaging")
        raise SystemExit(2)

APP_DIR = Path(__file__).resolve().parent
WHEEL_DIR = APP_DIR / ".wheels"
LIB_DIR = APP_DIR / ".pylibs"

PY_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
PY_TAG = f"cp{PY_VERSION.replace('.', '')}"

# Пакеты верхнего уровня: (имя, extra)
ROOTS = [("streamlit", None), ("qrcode", "pil")]

USER_AGENT = "magic-ball-setup/1.0"


def platform_tag() -> str:
    """Тег платформы текущей системы в форме, которую используют имена колёс."""
    platform = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    if platform.startswith("macosx"):
        return platform  # macosx_11_0_arm64, macosx_10_9_x86_64
    return platform  # win_amd64, win_arm64, linux_x86_64


def platform_tags() -> set[str]:
    """Теги колёс, подходящие текущей системе: сначала своя платформа, потом any."""
    platform = platform_tag()
    tags = {f"{PY_TAG}-{PY_TAG}-{platform}", f"{PY_TAG}-abi3-{platform}", f"{PY_TAG}-none-{platform}"}
    if platform.startswith("linux"):
        machine = platform.split("_", 1)[1]
        # manylinux-теги: своё колесо всегда предпочтительнее чистого linux
        for manylinux in (f"manylinux_2_39_{machine}", f"manylinux_2_35_{machine}",
                          f"manylinux_2_31_{machine}", f"manylinux_2_28_{machine}",
                          f"manylinux_2_17_{machine}", f"manylinux2014_{machine}"):
            tags.add(f"{PY_TAG}-{PY_TAG}-{manylinux}")
            tags.add(f"{PY_TAG}-abi3-{manylinux}")
    if platform == "win_amd64":
        # часть пакетов (watchdog, pywin32-обвязки) выпускает колёса без CPython-тега
        tags.add("py3-none-win_amd64")
    tags.add(f"py{PY_VERSION.replace('.', '')}-none-any")
    tags.add("py3-none-any")
    return tags


TAGS = platform_tags()
IS_PURE = platform_tag() == "any"


def log(message: str) -> None:
    print(message, flush=True)


def fetch_json(name: str) -> dict:
    url = f"https://pypi.org/pypi/{name}/json"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _expand(tag: str) -> list[str]:
    """py2.py3 -> [py2, py3]: в колесе теги бывают сжаты через точку."""
    return tag.split(".")


def wheel_tags(filename: str) -> set[str]:
    parts = filename[: -len(".whl")].split("-")
    pytag, abitag, platformtag = parts[-3], parts[-2], parts[-1]
    return {
        f"{py}-{abi}-{platform}"
        for py in _expand(pytag)
        for abi in _expand(abitag)
        for platform in _expand(platformtag)
    }


def pick_wheel(name: str, version: str, files: list[dict]) -> dict | None:
    """Выбирает колесо: сначала родная платформа (их может быть несколько версий), потом any."""
    canon = canonicalize_name(name)
    platform = platform_tag()
    native_platform: list[dict] = []
    native_abi3: list[dict] = []
    pure: list[dict] = []
    for entry in files:
        filename = entry.get("filename", "")
        if not filename.endswith(".whl") or entry.get("yanked"):
            continue
        parts = filename[: -len(".whl")].split("-")
        if len(parts) < 5:
            continue
        if canonicalize_name(parts[0].replace("_", "-")) != canon or parts[1] != version:
            continue
        pytag, abitag, platformtag = parts[-3], parts[-2], parts[-1]
        if not (wheel_tags(filename) & TAGS):
            continue
        expanded_platforms = _expand(platformtag)
        if all(tag == "any" for tag in expanded_platforms):
            pure.append(entry)
        elif platform in expanded_platforms and PY_TAG in _expand(pytag):
            native_platform.append(entry)
        elif platform in expanded_platforms:
            native_abi3.append(entry)

    for bucket in (native_platform, native_abi3, pure):
        if bucket:
            # при равной платформе берём самое свежее колесо по имени
            bucket.sort(key=lambda entry: entry["filename"], reverse=True)
            return bucket[0]
    return None


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            handle.write(chunk)


def unpack(wheel: Path) -> int:
    count = 0
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = LIB_DIR / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as destination:
                destination.write(source.read())
            count += 1
    return count


def resolver_environment(extra: str | None) -> dict[str, str]:
    return {
        "extra": extra or "",
        "python_version": PY_VERSION,
        "python_full_version": sys.version.split()[0],
        "sys_platform": sys.platform,
        "platform_system": {"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, "Linux"),
        "platform_machine": "AMD64" if sys.maxsize > 2**32 else "x86",
        "os_name": "nt" if sys.platform == "win32" else "posix",
        "implementation_name": sys.implementation.name,
        "platform_python_implementation": "CPython",
    }


def choose_release(canon: str, specifier, data: dict) -> tuple[str, dict] | None:
    """Ищет версию с подходящим колесом: свежие релизы вниз, затем пре-релизы.

    Нужно для пакетов, которые выкинули поддержку платформы в свежем релизе:
    например, watchdog 6 больше не собирается под Windows, поэтому берём 5.x.
    """
    candidates: list[tuple[Version, dict, dict]] = []
    for raw_version, files in data.get("releases", {}).items():
        try:
            version = Version(raw_version)
        except InvalidVersion:
            continue
        if specifier is not None and version not in specifier:
            continue
        usable = [entry for entry in files if not entry.get("yanked")]
        if not usable:
            continue
        wheel = pick_wheel(canon, raw_version, usable)
        if wheel is not None:
            candidates.append((version, {"info": data["info"], "urls": usable, "version": raw_version}, wheel))

    if not candidates:
        return None

    stable = [item for item in candidates if not item[0].is_prerelease]
    pool = stable or candidates
    pool.sort(key=lambda item: item[0], reverse=True)
    version, release, _wheel = pool[0]
    return release["version"], release


def resolve() -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    failures: list[str] = []
    queue: list[tuple[str, str | None, SpecifierSet | None]] = [(*root, None) for root in ROOTS]

    while queue:
        raw_name, extra, specifier = queue.pop(0)
        canon = canonicalize_name(raw_name)
        if canon in resolved:
            continue
        try:
            data = fetch_json(canon)
        except urllib.error.HTTPError as exc:
            failures.append(f"{canon}: HTTP {exc.code}")
            continue

        chosen = choose_release(canon, specifier, data)
        if chosen is None:
            wanted = f" (нужно {specifier})" if specifier else ""
            failures.append(f"{canon}: нет релиза с колесом для этой системы{wanted}")
            continue

        version, release = chosen
        latest = data["info"]["version"]
        if version != latest:
            log(f"[откат] {canon}: свежий {latest} не подходит, беру {version}")
        resolved[canon] = version
        log(f"[найдено] {canon}=={version}")

        for raw in release["info"].get("requires_dist") or []:
            try:
                requirement = Requirement(raw)
            except Exception:
                continue
            if requirement.marker is not None:
                try:
                    if not Marker(str(requirement.marker)).evaluate(resolver_environment(extra)):
                        continue
                except Exception:
                    continue
            if requirement.extras and not extra:
                continue
            queue.append((
                requirement.name,
                next(iter(requirement.extras)) if requirement.extras else None,
                requirement.specifier if str(requirement.specifier) else None,
            ))

    return resolved, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Скачать зависимости в .pylibs без pip")
    parser.add_argument("--clean", action="store_true", help="удалить .pylibs и .wheels перед загрузкой")
    parser.add_argument("--dry-run", action="store_true", help="только показать, что будет скачано")
    args = parser.parse_args()

    if args.clean:
        for path in (LIB_DIR, WHEEL_DIR):
            shutil.rmtree(path, ignore_errors=True)
            log(f"[очистка] {path.name}")

    WHEEL_DIR.mkdir(parents=True, exist_ok=True)
    LIB_DIR.mkdir(parents=True, exist_ok=True)

    log(f"[система] python {PY_VERSION}, платформа {platform_tag()}")
    resolved, failures = resolve()
    log(f"\n[итог] пакетов: {len(resolved)}, проблем: {len(failures)}")
    for problem in failures:
        log(f"  !! {problem}")

    if args.dry_run:
        for canon in sorted(resolved):
            log(f"  {canon}=={resolved[canon]}")
        return 1 if failures else 0

    for canon in sorted(resolved):
        version = resolved[canon]
        destination = WHEEL_DIR / f"{canon.replace('-', '_')}-{version}.whl"
        if destination.exists():
            continue
        data = fetch_json(canon)
        wheel = pick_wheel(canon, version, data["urls"])
        if wheel is None:
            failures.append(f"{canon}: колесо исчезло с PyPI")
            continue
        log(f"[скачано] {wheel['filename']}")
        download(wheel["url"], destination)

    total = 0
    for wheel in sorted(WHEEL_DIR.glob("*.whl")):
        total += unpack(wheel)
    log(f"[распаковано] файлов: {total} -> {LIB_DIR}")

    if failures:
        log("[провал] " + "; ".join(failures))
        return 1
    log("[готово] зависимости на месте, запускайте run.ps1 (или ./start.sh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
