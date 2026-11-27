"""Validate and summarize experiment A in the shared experiment_results.txt schema."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

VARIANTS = ("flex", "re2c", "table", "branch")
ORDERS = (("flex", "re2c", "branch", "table"), ("re2c", "table", "flex", "branch"),
          ("table", "branch", "re2c", "flex"), ("branch", "flex", "table", "re2c"))
FIELDS = ("experiment", "input_id", "variant", "rounds", "bytes", "tokens",
          "median_ns_per_byte", "q1_ns_per_byte", "q3_ns_per_byte")


def q(values, p):
    data = sorted(values)
    position = (len(data) - 1) * p
    low = int(position)
    return data[low] + (data[min(low + 1, len(data) - 1)] - data[low]) * (position - low)


def summarize(directory):
    inputs = json.loads((directory / "inputs.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((directory / "measurements.csv").open(encoding="utf-8", newline="")))
    assert len(rows) == len(inputs) * 64 == 640
    metadata = {item["name"]: item for item in inputs}
    validation = {row["input"]: row for row in csv.DictReader((directory / "validation.csv").open(encoding="utf-8"))}
    grouped = defaultdict(list)
    rounds = defaultdict(dict)
    for row in rows:
        assert row["experiment"] == "A" and row["variant"] in VARIANTS
        item = metadata[row["input_id"]]
        assert row["input_sha256"] == item["sha256"]
        assert int(row["bytes"]) == item["bytes"] and int(row["tokens"]) == item["tokens"]
        assert row["checksum"] == validation[row["input_id"]]["checksum"]
        assert validation[row["input_id"]]["full_token_match"] == validation[row["input_id"]]["eof_match"] == "true"
        round_number, order = int(row["round"]), int(row["order"])
        assert 1 <= round_number <= 16 and 1 <= order <= 4
        assert ORDERS[(round_number - 1) % 4][order - 1] == row["variant"]
        assert int(row["elapsed_ns"]) > 0
        key = (row["input_id"], round_number)
        assert row["variant"] not in rounds[key], "duplicate observation"
        rounds[key][row["variant"]] = int(row["elapsed_ns"])
        grouped[(row["input_id"], row["variant"])].append(int(row["elapsed_ns"]) / int(row["bytes"]))
    result = []
    for item in inputs:
        for variant in VARIANTS:
            values = grouped[(item["name"], variant)]
            assert len(values) == 16
            result.append(dict(zip(FIELDS, ("A", item["name"], variant, 16, item["bytes"], item["tokens"],
                                          q(values, .5), q(values, .25), q(values, .75)))))
    for pair in rounds.values():
        assert set(pair) == set(VARIANTS)
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(result)
    return inputs, result, rounds


def write_report(directory, output):
    inputs, stats, rounds = summarize(directory)
    data = {(row["input_id"], row["variant"]): row for row in stats}
    env = json.loads((directory / "environment.json").read_text(encoding="utf-8"))
    coverage = json.loads((directory / "coverage.json").read_text(encoding="utf-8"))
    inventory = json.loads((directory / "textbook_inventory.json").read_text(encoding="utf-8"))
    def cell(name, variant):
        row = data[(name, variant)]
        return f"{row['median_ns_per_byte']:.3f} [{row['q1_ns_per_byte']:.3f}; {row['q3_ns_per_byte']:.3f}]"
    def median(name, variant):
        return data[(name, variant)]["median_ns_per_byte"]
    leaders = Counter()
    for item in inputs:
        leaders[min(VARIANTS, key=lambda variant: median(item["name"], variant))] += 1
    lines = ["# Эксперимент А: сравнение четырёх сканеров", "",
             f"Сеанс `{directory.name}`, начало {env['started_moscow']}.", "",
             "На подготовленном учебном корпусе получены следующие времена, нс/байт:", ""]
    for variant in VARIANTS:
        lines.append(f"- **{variant}**: {cell('textbook', variant)}.")
    lines += ["", "Здесь и далее указаны медиана [Q1; Q3] по 16 проходам.",
              "По наименьшей медиане на десяти входах: " + ", ".join(f"{variant} — {leaders[variant]}" for variant in VARIANTS) + ".",
              "Это описывает только выбранные файлы и данную сборку. Степень устойчивости",
              "порядка приведена отдельно; квартили не являются доверительными интервалами.", "",
              "## Постановка и условия", "",
              "Лексика — `spec/scanner_spec.txt`; основа — псевдокод § 0.2.4, регулярные",
              "операции § 1.2.1–1.2.2 и лексические единицы § 3.2.1 учебника.",
              "Табличное вычисление δ соответствует § 2.6.1, ветвления — § 2.6.2.",
              "В опыте А сравниваются реализации целиком: внутренние автоматы flex и re2c",
              "могут отличаться от собственного ДКА. Разницу времени нельзя целиком приписать δ.", "",
              f"- CPU: {env['cpu']}, {env['logical_cpus']} логических процессоров; память {env['physical_memory_bytes']/2**30:.2f} ГиБ.",
              f"- ОС: {env['platform']}.",
              f"- C: `{env['c_version']}`; C++: `{env['cxx_version']}`.",
              f"- Генераторы: `{env['flex_version']}`, `{env['re2c_version']}`; flex: `-8 -Cf`.",
              "- Одна Release-сборка: `-O3 -DNDEBUG`; генераторы выдают C11, собственный сканер — C++17.",
              "  Точные команды с фактическими стандартами и определениями находятся в environment.json и run.txt.",
              "- Монотонные часы Windows QueryPerformanceCounter. Один прогрев на вариант и файл,",
              "  затем 16 раундов. Открытие, копирование буфера, закрытие, дисковый ввод, сверка и CSV — вне таймера.",
              "- В интервал входят next, счётчик K и одинаковая checksum по kind, begin, end (EOF учтён в сумме, но не в K).",
              "- Порядок четырёх раундов из инструкции повторён четыре раза; каждый сканер занимает каждое место четыре раза.",
              "- Привязка к ядру не задавалась, приоритет обычный; фоновые процессы и частоты ОС не контролировались.", "",
              "## Учебный корпус и охват", "",
              f"Вход textbook — неизменённый `pseudocode/pseudocode.txt`: {inputs[0]['bytes']} байт, {inputs[0]['tokens']} лексем.",
              f"Выделено {inventory['fragment_count']} фрагмента(ов), полный перечень — textbook_inventory.json.",
              "`pseudocode/run.txt` содержит команду извлечения и входом сканера не является.",
              "Допустимые замены сохранены в pseudocode_translation.json и в снимке исходников:",
              "присваивание → :=, математические имена → латинские обозначения, интервалы → to,",
              "символьные литералы → имена вроде leftParen; комментарии сохраняют исходные байты.",
              "Для каждого фрагмента отмечены только подтверждённые точным нормализованным совпадением параграфы.",
              "Часть фрагментов получена ранее из исходников GA, отсутствующих в текущем дереве;",
              "для них точная атрибуция не выдумывается. Проверенные разделы включают:", ""]
    sections = sorted({section for item in inventory["fragments"] for section in item["verified_sections"]})
    lines += ["- " + section for section in sections]
    lines += ["", f"Нагрузочные входы покрывают {coverage['covered_kind_count']} из {coverage['ordinary_kind_count']} обычных видов лексем.",
              "Отсутствуют в нагрузках: " + (", ".join(coverage["missing_from_workloads"]) or "нет") + ".",
              "Все обычные виды, включая отсутствующие в нагрузках, отдельно проверены на коротких контрольных примерах",
              "у каждого сканера. Это не добавляет их в нагрузочный корпус.", "",
              "Девять искусственных файлов и textbook совпадают с байтами опыта Б по SHA-256.",
              "Имена skip_space/skip_comment соответствуют skip_spaces/skip_comments в Б,",
              "size_small/medium/large — mixed_2048/32768/524288. Сопоставление и хеши — inputs.json.", "",
              "| Вход | Источник / рецепт | Что меняется | Что фиксировано | N | K |",
              "| --- | --- | --- | --- | ---: | ---: |"]
    varying = {"textbook": ("учебный состав", "байты подготовленного корпуса"),
               "I_prefix": ("общее начало с if", "N, K, виды, границы"),
               "II_length": ("длина идентификатора и доля разделителей", "N и вид TOK_IDENT"),
               "III_skip": ("правило пропуска", "N, K и границы"),
               "IV_size": ("число целых блоков", "состав и длины лексем")}
    for item in inputs:
        varied, fixed = varying[item["family"]]
        lines.append(f"| {item['name']} | `{item['recipe']}` | {varied} | {fixed} | {item['bytes']} | {item['tokens']} |")
    lines += ["", "## Проверка и замеры", "",
              "Перед основной серией каждый из четырёх потоков лексем сверен с независимыми",
              "ожидаемыми тройками (kind,begin,end) на всех десяти файлах, включая самый большой.",
              "Проверены EOF ровно на N и повторный EOF. Короткие проверки включают пустой вход,",
              "if, if2, if:=15, неизвестный байт, комментарий до EOF с NUL/0xFF и повтор после ошибки.",
              "В каждом замере совпали K и checksum; ошибок и преждевременного EOF не было.",
              "Записано ровно 640 измерений и 40 сводных строк. Прогревы не включены, выбросы не удалялись.", "",
              "| Вход | N, байт | K | flex, нс/байт | re2c, нс/байт | table, нс/байт | branch, нс/байт |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for item in inputs:
        lines.append(f"| {item['name']} | {item['bytes']} | {item['tokens']} | " + " | ".join(cell(item['name'], variant) for variant in VARIANTS) + " |")
    lines += ["", "Квартили рассчитаны линейной интерполяцией по (n−1)p, p = 0.25, 0.50, 0.75.", "",
              "## Сопоставление серий", "",
              "Сначала учебный текст: результаты всех четырёх участников приведены в начале",
              "отчёта и в общей таблице. В следующих сериях сравниваются медианы того же участника",
              "на двух разных файлах; это отношения медиан, а не парные отношения опыта Б.", ""]
    for title, first, second in (("I. Общие начала", "prefix_abx", "prefix_ifx"),
                                  ("II. Длина идентификатора", "ident_3", "ident_15"),
                                  ("III. Пропуски", "skip_space", "skip_comment")):
        lines += [f"**{title}: {first} → {second}.**", ""]
        for variant in VARIANTS:
            lines.append(f"- {variant}: {cell(first, variant)} → {cell(second, variant)} нс/байт; "
                         f"отношение медиан {median(second, variant)/median(first, variant):.3f}.")
        lines.append("")
    lines += ["В I позиции лексем одинаковы. Ключевые слова у flex/re2c заданы отдельными",
              "приоритетными правилами генератора; собственный ДКА использует состояния префиксов.",
              "В II K уменьшается вчетверо и меняется доля пробелов: цену отдельной выдачи лексемы",
              "эти данные не изолируют. В III меняется только путь обработки пропускаемого участка.", "",
              "**IV. Рост размера при неизменном составе.** В блоке 30 байт и 9 лексем;",
              "размеры 61 440, 983 040 и 15 728 640 байт получены без обрезания блоков.", "",
              "| Вариант | small, мс | medium, мс | large, мс | small → medium → large, нс/байт |",
              "| --- | ---: | ---: | ---: | --- |"]
    for variant in VARIANTS:
        names = ("size_small", "size_medium", "size_large")
        times = [median(name, variant) * data[(name, variant)]["bytes"] / 1e6 for name in names]
        lines.append(f"| {variant} | " + " | ".join(f"{value:.3f}" for value in times) + " | " +
                     " → ".join(f"{median(name, variant):.3f}" for name in names) + " |")
    lines += ["", "Разброс времени на байт для всех размеров указан в основной таблице.",
              "Различия нельзя автоматически объяснять кешем или предсказанием ветвлений:",
              "аппаратные счётчики здесь не измерялись.", "",
              "## Устойчивость порядка", "",
              "Число первых мест в 16 раундах (при равенстве минимум засчитывается всем равным):", "",
              "| Вход | flex | re2c | table | branch |", "| --- | ---: | ---: | ---: | ---: |"]
    for item in inputs:
        wins = Counter()
        for number in range(1, 17):
            pair = rounds[(item["name"], number)]
            wins.update(variant for variant in VARIANTS if pair[variant] == min(pair.values()))
        lines.append(f"| {item['name']} | " + " | ".join(str(wins[variant]) for variant in VARIANTS) + " |")
    lines += ["", "Если первые места распределены между вариантами, порядок в отдельных раундах",
              "менялся. Малые различия при перекрывающихся диапазонах следует считать неопределёнными",
              "в пределах этой серии; по лучшему одиночному времени победитель не выбирается.", "",
              "Результат относится к согласованной лексике, этим входам, компилятору и повторному",
              "сканированию текста в памяти. Причины разницы только в представлении одной δ",
              "исследуются отдельно в Б; сведения о flex/re2c из А такого вывода не дают.", "",
              "## Файлы и воспроизведение", "",
              f"Основные данные: `results/{directory.name}/run.txt`, `measurements.csv`, `summary.csv`.",
              "Проверка: validation.csv, control_tests.log, preflight.log; условия: environment.json.",
              "Исходники, сгенерированные C-файлы и входной textbook сохранены в source_snapshot.zip;",
              "SHA-256 — source_hashes.json и inputs.json. Большие искусственные входы воспроизводятся рецептами.", "",
              "Из корня проекта:", "", "```sh", "python experiments/a/run_experiment.py", "```", "",
              "Пересчёт из сохранённых CSV без измерений:", "", "```sh",
              f"python experiments/a/summarize.py experiments/a/results/{directory.name}", "```", ""]
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    for item in inputs:
        print(item["name"] + ": " + "; ".join(variant + " " + cell(item["name"], variant) for variant in VARIANTS), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report:
        write_report(args.directory, args.report)
    else:
        summarize(args.directory)
