"""Recompute statistics from all 16 paired rounds; no benchmarking occurs here."""

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path


def quantiles(values):
    # Linear interpolation at (n-1)*p (Hyndman-Fan type 7).
    data = sorted(values)
    def q(p):
        index = (len(data) - 1) * p
        low = int(index)
        return data[low] + (data[min(low + 1, len(data) - 1)] - data[low]) * (index - low)
    return q(0.25), statistics.median(data), q(0.75)


def summarize(directory):
    inputs = json.loads((directory / "inputs.json").read_text(encoding="utf-8"))
    groups = defaultdict(dict)
    for row in csv.DictReader((directory / "samples.csv").open(encoding="utf-8", newline="")):
        key = (row["input"], int(row["round"]))
        assert row["variant"] not in groups[key], "duplicate sample"
        groups[key][row["variant"]] = row
    validation = {row["input"]: row for row in csv.DictReader((directory / "validation.csv").open(encoding="utf-8"))}
    summaries = []
    pair_rows = []
    for item in inputs:
        name = item["name"]
        assert validation[name]["full_token_match"] == validation[name]["eof_match"] == "true"
        times = {"table": [], "branch": []}
        ratios = []
        for round_number in range(1, 17):
            pair = groups.pop((name, round_number))
            assert set(pair) == {"table", "branch"}
            for variant, row in pair.items():
                assert int(row["bytes"]) == item["bytes"] and int(row["tokens"]) == item["tokens"]
                assert row["checksum"] == validation[name]["checksum"]
                expected_order = 1 if (variant == "table") == (round_number % 2 == 1) else 2
                assert int(row["order"]) == expected_order
                times[variant].append(float(row["elapsed_ns"]))
            ratio = float(pair["table"]["elapsed_ns"]) / float(pair["branch"]["elapsed_ns"])
            ratios.append(ratio)
            pair_rows.append({"input": name, "round": round_number, "table_over_branch": ratio})
        summary = {"input": name, "family": item["family"], "bytes": item["bytes"], "tokens": item["tokens"]}
        for variant in times:
            low, median, high = quantiles(times[variant])
            summary.update({f"{variant}_median_ns": median, f"{variant}_min_ns": min(times[variant]),
                f"{variant}_max_ns": max(times[variant]), f"{variant}_q1_ns_per_byte": low / item["bytes"],
                f"{variant}_median_ns_per_byte": median / item["bytes"],
                f"{variant}_q3_ns_per_byte": high / item["bytes"],
                f"{variant}_median_tokens_per_second": item["tokens"] * 1e9 / median})
        low, median, high = quantiles(ratios)
        summary.update({"ratio_q1": low, "ratio_median": median, "ratio_q3": high,
                        "table_faster_rounds": sum(ratio < 1 for ratio in ratios),
                        "branch_faster_rounds": sum(ratio > 1 for ratio in ratios)})
        summaries.append(summary)
    assert not groups, "unrecognized samples"
    for filename, rows in (("summary.csv", summaries), ("paired_ratios.csv", pair_rows)):
        with (directory / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return summaries


def report(directory, output):
    rows = summarize(directory)
    by_name = {row["input"]: row for row in rows}
    metadata = json.loads((directory / "environment.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((directory / "dfa_diagnostics.json").read_text(encoding="utf-8"))
    timer = re.search(r"empty interval min=([0-9.]+) ns, mean=([0-9.]+) ns",
                      (directory / "benchmark.log").read_text(encoding="utf-8"))
    timer_mean = float(timer[2])
    table_wins = sum(row["ratio_median"] < 1 for row in rows)
    branch_wins = sum(row["ratio_median"] > 1 for row in rows)
    def fmt(name, variant):
        row = by_name[name]
        return (f"{row[variant + '_median_ns_per_byte']:.3f} "
                f"[{row[variant + '_q1_ns_per_byte']:.3f}; {row[variant + '_q3_ns_per_byte']:.3f}]")
    def ratio(name):
        row = by_name[name]
        return f"{row['ratio_median']:.3f} [{row['ratio_q1']:.3f}; {row['ratio_q3']:.3f}]"
    lines = [
        "# Результаты эксперимента Б: таблица и ветвления", "",
        f"Дата запуска: {metadata['started_moscow']}. Полные данные: `results/{directory.name}/`.", "",
        f"По медианам table быстрее на {table_wins} входах из {len(rows)}, branch — на {branch_wins}.",
        "Отношение времён зависит от лексического состава; универсального преимущества",
        "одного представления на всём наборе нет. Числа и разброс для каждого входа приведены ниже.", "",
        "Измерен полный проход собственного сканера до EOF при замене только способа",
        "вычисления δ. Лексика, граф, классы байтов и общий алгоритм `next` совпадают.", "",
        "## Условия", "",
        f"- Процессор: {metadata['cpu']}; логических процессоров: {metadata['logical_cpus']}.",
        f"- ОС: {metadata['platform']}; память: {metadata['physical_memory_bytes'] / 2**30:.2f} ГиБ.",
        f"- Компилятор C: `{metadata['c_version']}`; C++: `{metadata['cxx_version']}`.",
        "- Release: C11 для измерителя, C++17 для обоих вариантов ДКА; `-O3 -DNDEBUG`.",
        "  Без LTO и без принудительного запрета оптимизации switch; оба варианта в одном объектном файле.",
        "- Windows: QueryPerformanceCounter; на POSIX реализация использует CLOCK_MONOTONIC.",
        "- В память один раз загружается каждый файл. `open`, `close`, чтение, проверка",
        "  ожидаемых результатов и запись CSV находятся вне таймера.",
        "- Один прогрев каждого варианта на файле, затем 16 пар. В нечётных раундах",
        "  table запускается первым, в чётных — branch. Варианты выполняются последовательно.",
        "- Во время прохода общая для обоих вариантов 64-битная контрольная сумма",
        "  учитывает kind, begin, end каждой лексемы, включая EOF. K не включает EOF.",
        "- Медиана и квартили рассчитаны по 16 повторам, квартили — линейная интерполяция",
        "  в позиции (n−1)p (тип 7). Отношения вычисляются внутри каждой пары, затем агрегируются.",
        "- Обычный приоритет процесса, привязка к ядру не задавалась; фоновые процессы",
        "  и автоматическое управление частотой ОС не отключались.", "",
        "## Проверка корректности", "",
        f"Проверены все {diagnostics['state_count']} × 256 = {diagnostics['state_byte_pairs']} пар состояния и байта",
        "через ту же классификацию входного байта, что использует сканер.",
        "Существующие проверки прошли на 81 685 входах, включая ручные примеры,",
        "ошибку, повторные терминальные ответы и границы буфера. Для каждого нагрузочного",
        "файла оба варианта сверены по каждой тройке (kind,begin,end) с независимой",
        "последовательностью, подготовленной Python-генератором. EOF расположен ровно в N.",
        "В каждом измеренном проходе число лексем и checksum совпали с проверочным проходом.",
        "Подтверждение: `correctness.log`, `validation.csv`, `benchmark.log`.", "",
        "## Сводка", "",
        "Время приведено в нс/байт: медиана [Q1; Q3]. Отношение table/branch > 1",
        "означает меньшее время branch. Отношение < 1 означает меньшее время table.", "",
        "| Вход | N, байт | K, лексем | table, нс/байт | branch, нс/байт | table/branch | branch быстрее, раундов |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        name = row["input"]
        lines.append(f"| {name} | {row['bytes']} | {row['tokens']} | {fmt(name, 'table')} | {fmt(name, 'branch')} | {ratio(name)} | {row['branch_faster_rounds']}/16 |")
    short_min = min(by_name["textbook"][variant + "_min_ns"] for variant in ("table", "branch"))
    lines += ["", f"Средний пустой интервал двух чтений часов: {timer_mean:.1f} нс (10 000 пар).",
              f"Минимальный проход короткого учебного файла: {short_min:.0f} нс —",
              f"в {short_min / timer_mean:.0f} раз больше пустого интервала. Удлинённая версия",
              "дополнительно исключает зависимость вывода от одного короткого прохода.", "",
              "Дополнительные показатели, включая медианное время прохода, минимум/максимум",
              "и K/T (лексем/с), записаны в `summary.csv`. Все 352 исходных замера — в `samples.csv`.",
              "176 отношений пар — в `paired_ratios.csv`. Отброса отдельных замеров не было.", "",
              "## Разбор результатов", ""]
    for name in ("textbook", "textbook_long"):
        row = by_name[name]
        lines.append(f"На учебном входе `{name}` при N={row['bytes']} и K={row['tokens']} table дало "
                     f"{fmt(name, 'table')} нс/байт, branch — {fmt(name, 'branch')}; "
                     f"медиана парного отношения {ratio(name)}.")
        lines.append("")
    lines += [
        "Учебный образец взят из готового `pseudocode/pseudocode.txt` без правок.",
        "`pseudocode/run.txt` содержит команду извлечения, поэтому не использован как вход.",
        "Таблица преобразований — `pseudocode/pseudocode_translation.json`. Готовый файл",
        "объединяет примеры курса; точной карты его строк на исходные параграфы в репозитории нет,",
        "поэтому он обозначен как общий учебный корпус, а не как отдельный пример § 2.6.1.",
        "Число целых копий длинного файла, распределения видов, доля пропусков, рецепты",
        "и SHA-256 фактических входов приведены в `inputs.json`.", "",
    ]
    for title, first, second, interpretation in (
        ("Общие префиксы (I)", "prefix_ifx", "prefix_abx",
         "Оба файла имеют одинаковые виды, позиции и длины лексем. Для ifx посещаются состояния префиксов ключевого слова, для abx сразу используется общее состояние идентификатора."),
        ("Частота завершения (II)", "ident_3", "ident_15",
         "При одинаковом N число лексем уменьшается в четыре раза, меняется и доля разделителей. Это сравнение полных проходов; отдельную цену завершения лексемы оно не выделяет."),
        ("Пропускаемые участки (III)", "skip_spaces", "skip_comments",
         "Здесь совпадают размер, число лексем и все их границы. Отличается путь по состояниям пропуска пробелов и комментария."),
    ):
        lines += [f"**{title}.** `{first}`: table {fmt(first, 'table')}, branch {fmt(first, 'branch')}, "
                  f"отношение {ratio(first)}. `{second}`: table {fmt(second, 'table')}, branch {fmt(second, 'branch')}, "
                  f"отношение {ratio(second)}. {interpretation}", ""]
    lines += ["**Рост размера (IV).** Один и тот же смешанный блок повторяется без обрезания;",
              "состав и длины лексем сохраняются. Получены следующие значения:", ""]
    for name in ("mixed_2048", "mixed_32768", "mixed_524288"):
        row = by_name[name]
        lines += [f"- N={row['bytes']}, K={row['tokens']}: table {fmt(name, 'table')}, "
                  f"branch {fmt(name, 'branch')}, отношение {ratio(name)}."]
    lines += ["", "**Устойчивость в этой серии.**", ""]
    for row in rows:
        if row["branch_faster_rounds"] == 16:
            conclusion = "branch быстрее во всех 16 парах"
        elif row["table_faster_rounds"] == 16:
            conclusion = "table быстрее во всех 16 парах"
        else:
            conclusion = (f"порядок менялся: branch быстрее в {row['branch_faster_rounds']}/16, "
                          f"table — в {row['table_faster_rounds']}/16; единого победителя всех пар нет")
        if row["ratio_q1"] <= 1 <= row["ratio_q3"]:
            conclusion += "; межквартильный диапазон включает единицу, устойчивое преимущество не установлено"
        lines += [f"- `{row['input']}`: {conclusion}; отношение {ratio(row['input'])}."]
    lines += ["", "Вывод относится к полному сканеру при указанной сборке и повторному чтению",
              "подготовленного текста из памяти. Он не измеряет изолированную стоимость δ.",
              "Различия путей подтверждаются графом (см. `dfa_diagnostics.json`); аппаратные",
              "причины, такие как промахи кеша или предсказателя, здесь не измерялись.",
              "Скорости flex/re2c в этом опыте не измерялись. Замена исходного switch",
              "машинной таблицей переходов управления возможна и не запрещалась.", "",
              "## Воспроизведение", "", "Из корня репозитория:", "", "```sh",
              "python experiments/b/run_experiment.py", "```", "",
              "Повторный расчёт статистики для уже сохранённого запуска:", "", "```sh",
              f"python experiments/b/summarize.py experiments/b/results/{directory.name}", "```", "",
              "У каждого запуска отдельная папка; исходные результаты не перезаписываются.",
              "`source_snapshot.zip`, `source_hashes.json` и `environment.json` фиксируют",
              "исходники, версии, флаги сборки, хеш исполняемого файла и условия запуска.", ""]
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report:
        report(args.directory, args.report)
    else:
        summarize(args.directory)
