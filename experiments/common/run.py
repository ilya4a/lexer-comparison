"""Build and run either experiment, publishing only completed results."""

import argparse
import csv
import datetime as dt
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from generate_inputs import ROOT, generate, token_ids


FIELDS = """measurements.csv — одна строка на вариант, вход и раунд.

input_id — имя входа; family — семейство:
  textbook — учебный корпус; prefix — общие префиксы с ключевыми словами;
  length — длина идентификаторов или чисел; skip — пробелы и комментарии;
  size — повторение одного смешанного блока.
input_sha256 — SHA-256 всех байтов входа.
variant — реализация сканера.
round — номер раунда (с 1); order — позиция варианта внутри раунда (с 1).
bytes — размер одного прохода, включая пропуски; tokens — число выданных
  лексем за один проход, без EOF.
passes — число полных проходов в интервале замера одного раунда.
elapsed_ns — суммарное время этих проходов в наносекундах.
checksum — 64-битная контрольная сумма одного прохода (hex). Начальное
  значение 14695981039346656037. Для kind, begin, end каждой лексемы и EOF
  применяются XOR и умножение на 1099511628211 по модулю 2^64.
  Каждый измеренный проход сверяется с эталонными K, EOF и checksum.

Время на проход = elapsed_ns / passes; время на байт = elapsed_ns /
(passes * bytes); миллионы лексем/с = 1000 * passes * tokens / elapsed_ns.
В REPORT.md приведены медиана и [Q1; Q3], с линейной интерполяцией по (n−1)p.
Отношение в Б — время table / branch внутри одного раунда; > 1 означает
меньшее время branch. Прогревы в CSV отсутствуют.
"""


def run(*args):
    command = [str(arg) for arg in args]
    process = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", check=False)
    if process.returncode:
        raise RuntimeError(f"{subprocess.list2cmdline(command)}\n{process.stdout.strip()}")
    return process.stdout.strip()


def cmake_cache(build):
    cache = build / "CMakeCache.txt"
    if not cache.is_file():
        return {}
    return {line.split(":", 1)[0]: line.split("=", 1)[1]
            for line in cache.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith(("//", "#")) and ":" in line and "=" in line}


def usable_build(path):
    build = path.resolve()
    for suffix in range(1, sys.maxsize):
        cache = cmake_cache(build)
        if not cache or (Path(cache.get("CMAKE_HOME_DIRECTORY", "")).resolve() == ROOT
                         and Path(cache.get("CMAKE_CACHEFILE_DIR", "")).resolve() == build):
            return build
        build = path.with_name(f"{path.name}.{suffix}").resolve()
    raise RuntimeError("No usable build directory")


def executable(build, target):
    name = target + (".exe" if os.name == "nt" else "")
    for candidate in (build / "Release" / name, build / name):
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"Executable missing: {name}")


def conditions(build, mode):
    cache = cmake_cache(build)
    system = platform.platform()
    cpu = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "")
    if not cpu and Path("/proc/cpuinfo").is_file():
        cpu = next((line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), platform.machine())
    tools = []
    for language in ("C", "CXX"):
        compiler = cache[f"CMAKE_{language}_COMPILER"]
        flags = " ".join(cache.get(f"CMAKE_{language}_FLAGS{suffix}", "").strip()
                         for suffix in ("", "_RELEASE")).strip()
        version = run(compiler, "--version").splitlines()[0]
        tools.append(f"{language}: {version} ({flags})")
    if mode == "a":
        tools.extend((run(cache["FLEX_EXECUTABLE"], "--version") + " (-8 -Cf)",
                      run(cache["RE2C_EXECUTABLE"], "--version")))
    revision = ""
    if (ROOT / ".git").exists() and shutil.which("git"):
        commit = run("git", "rev-parse", "HEAD")[:12]
        dirty = run("git", "status", "--porcelain", "--untracked-files=no")
        revision = f" Исходники {commit}" + (" с локальными правками." if dirty else ".")
    return f"{system}; {cpu or platform.machine()}. " + "; ".join(tools) + "." + revision


def interval(samples):
    quartiles = statistics.quantiles(samples, n=4, method="inclusive")
    return f"{statistics.median(samples):.3f} [{quartiles[0]:.3f}; {quartiles[2]:.3f}]"


def summarize(path, inputs, variants, rounds, mode, build_conditions):
    values = defaultdict(dict)
    by_id = {entry["name"]: entry for entry in inputs}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            entry = by_id[row["input_id"]]
            key = (row["input_id"], row["variant"])
            repetition = int(row["round"])
            order = (variants.index(row["variant"]) - repetition + 1) % len(variants) + 1
            size, tokens, passes = (int(row[field]) for field in ("bytes", "tokens", "passes"))
            if (repetition in values[key] or order != int(row["order"]) or
                (size, tokens, row["input_sha256"], row["family"]) !=
                    (entry["bytes"], entry["tokens"], entry["sha256"], entry["family"]) or
                passes != (16 if size < 65536 else 1)):
                raise ValueError(f"Некорректный замер: {row}")
            values[key][repetition] = float(row["elapsed_ns"]) / passes

    textbook = inputs[0]
    covered = {kind for entry in inputs for kind in entry["kind_counts"]}
    lines = [
        "# Опыт А" if mode == "a" else "# Опыт Б", "",
        build_conditions, "",
        "Release: измеритель" + (" и сгенерированные сканеры" if mode == "a" else "")
        + " на C11, собственный ДКА на C++17. Отдельная привязка к ядру не задаётся.", "",
        f"Сверка с эталоном и EOF пройдена. Входов {len(inputs)}, "
        f"раундов {rounds}. Порядок циклически сдвигается. "
        "Одна прогревочная серия на вариант и вход исключена из сводки.",
        "Монотонные часы измеряют вызовы next и учёт результата. "
        "Чтение с диска, подготовка состояний, сверка и запись выполняются вне интервала. "
        "Для входов меньше 64 КиБ раунд объединяет 16 проходов.",
        "",
        f"Покрытие нагрузок: {len(covered)}/{len(token_ids()) - 2} обычных видов. Учебный "
        f"корпус: {textbook['bytes']} байт, {textbook['tokens']} лексем, "
        f"{textbook['skip_byte_fraction']:.1%} пропускаемых байтов. "
        "Таблица замен хранится в pseudocode/pseudocode_translation.json.",
        "Частоты учебного корпуса: " + ", ".join(
            f"{kind[4:]} {count}" for kind, count in textbook["kind_counts"].items()) + ".",
        "Длины лексем (байт → частота): " + ", ".join(
            f"{length} → {count}" for length, count in textbook["token_lengths"].items()) + ".",
        "",
        "В ячейках медиана [Q1; Q3] в нс/байт и пропускная способность по медиане в млн лексем/с."
        + (" Последний столбец содержит парное отношение table/branch." if mode == "b" else ""),
        "",
    ]
    headers = ["Вход", "Байты", "Лексемы", *variants]
    if mode == "b":
        headers.append("table/branch")
    lines += ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for entry in inputs:
        name, size, tokens = (entry[field] for field in ("name", "bytes", "tokens"))
        cells = [name, str(size), str(tokens)]
        times = []
        for variant in variants:
            samples = values[(name, variant)]
            if set(samples) != set(range(1, rounds + 1)):
                raise ValueError(f"Неполная серия: {name}/{variant}")
            ordered = [samples[i] for i in range(1, rounds + 1)]
            times.append(ordered)
            cells.append(interval([elapsed / size for elapsed in ordered])
                         + f"; {1000 * tokens / statistics.median(ordered):.1f}")
        if mode == "b":
            cells.append(interval([table / branch for table, branch in zip(*times)]))
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "**Рецепты.** " + " · ".join(
        f"{entry['name']} — {entry['recipe']}"
        + (f", ×{entry['copies']}" if entry["copies"] > 1 else "")
        + (f", затем {entry['padding']} пробелов" if entry["padding"] else "")
        for entry in inputs) + ".", ""]
    return "\n".join(lines)


def main(mode):
    parser = argparse.ArgumentParser(description=f"Запуск опыта {mode.upper()}")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build" / f"experiment_{mode}")
    parser.add_argument("--run-id")
    if mode == "a":
        parser.add_argument("--flex")
        parser.add_argument("--re2c")
    args = parser.parse_args()
    now = dt.datetime.now().astimezone()
    run_id = args.run_id or now.strftime("%Y-%m-%d_%H%M%S_%f")
    if Path(run_id).name != run_id or run_id in ("", ".", ".."):
        parser.error("run-id must be one directory name")

    destination = ROOT / "experiments" / mode / "results" / run_id
    if destination.exists():
        parser.error(f"Run already exists: {destination}")
    a = mode == "a"
    variants = ("flex", "re2c", "table") if a else ("table", "branch")
    target = f"experiment_{mode}"
    build = usable_build(args.build_dir)
    configure = ["cmake", "-S", ROOT, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
                 f"-DSNIRS_BUILD_GENERATED_SCANNERS={'ON' if a else 'OFF'}"]
    if os.name == "nt" and not cmake_cache(build):
        configure += ["-G", "MinGW Makefiles"]
    if a:
        for explicit, key, command, fallback in (
            (args.flex, "FLEX", "flex", ROOT / "build/tools/winflexbison/win_flex.exe"),
            (args.re2c, "RE2C", "re2c", ROOT / "build/tools/re2c-build/re2c.exe"),
        ):
            tool = explicit or shutil.which(command) or (fallback if fallback.is_file() else None)
            if tool:
                configure.append(f"-D{key}_EXECUTABLE={Path(tool).resolve().as_posix()}")

    try:
        run(*configure)
        check_target = "scanner_tests" if a else "experiment_b_checks"
        run("cmake", "--build", build, "--config", "Release", "--target", target, check_target)
        if a:
            run(executable(build, check_target), ROOT / "pseudocode/pseudocode.txt")
        else:
            run(executable(build, check_target))
            run(sys.executable, ROOT / "snirs-dfa/table/generate_dfa.py", "--check")

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="run-", dir=build) as workdir, \
                tempfile.TemporaryDirectory(prefix=".pending-", dir=destination.parent) as stage:
            inputs = generate(Path(workdir))
            output = Path(stage) / run_id
            output.mkdir()
            samples = output / "measurements.csv"
            run(executable(build, target), Path(workdir) / "manifest.tsv", samples)
            report = summarize(samples, inputs, variants, 15 if a else 16, mode, conditions(build, mode))
            (output / "REPORT.md").write_text(report, encoding="utf-8")
            (output / "fields.txt").write_text(FIELDS, encoding="utf-8")
            output.rename(destination)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(destination.relative_to(ROOT))
