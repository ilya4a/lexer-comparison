# Эксперимент Б

Сравнение `scanner_table` и `scanner_branch` по `experiment_b_guide.txt`.
Последний фактический запуск описан в [RESULTS.md](RESULTS.md).
Исходные измерения и снимки исходников сохраняются в `results/<run_id>/`;
рабочие копии — в `build/results/<run_id>/`.

Из корня репозитория:

```sh
python experiments/b/run_experiment.py
```

Нужны Python 3.10+, CMake и GCC/G++ (MinGW в Windows). Генераторы flex/re2c
не требуются. Опыт А не запускается. Существующая C++17-библиотека ДКА
связывается с измерителем на C11; отдельной реализации сканера здесь нет.

Ручная сборка:

```sh
cmake -S . -B build/experiment_b -DCMAKE_BUILD_TYPE=Release -DSNIRS_BUILD_GENERATED_SCANNERS=OFF
cmake --build build/experiment_b --target experiment_b experiment_b_checks
ctest --test-dir build/experiment_b --output-on-failure
python experiments/common/generate_inputs.py
```

В Windows для CMake выберите генератор `-G "MinGW Makefiles"`.
Раннер делает это автоматически и фиксирует пути обоих компиляторов.

Измеритель вызывается с тремя аргументами: TSV-перечень входов, путь выходного
`samples.csv`, путь `validation.csv`. TSV содержит четыре поля без заголовка:
имя входа, семейство, путь байтового файла, путь ожидаемых лексем.
Перед замерами производится полная сверка обоих сканеров с независимым
ожидаемым потоком троек, записанным генератором в `<IQQ` little endian.
Любое расхождение или ошибка вместо EOF прерывает запуск.

Схема `samples.csv`: `input,family,bytes,tokens,round,order,variant,elapsed_ns,`
`ns_per_byte,tokens_per_second,checksum`. Для каждого из 11 входов — 16 пар,
то есть 352 строки. Начальное значение checksum — 14695981039346656037;
для каждого поля kind, begin, end выполняются XOR с полем и умножение
на 1099511628211 по модулю 2^64. EOF входит в сумму, но не в число K.
`validation.csv` подтверждает полное совпадение тройки каждой лексемы с эталоном.
Файл `experiment_results.txt`, упомянутый в руководстве, в репозитории отсутствует;
используется описанная здесь явная схема.

Время включает только цикл `next` и учёт лексем; `open`, `close`, дисковый ввод,
печать, подготовка входа и сверка исключены. По одному прогреву на вариант
и вход; затем 16 раундов с порядком table→branch и branch→table попеременно.
Нет фильтрации выбросов или автоматического повторения «плохих» результатов.

Пересчёт сохранённых измерений без нового запуска сканеров:

```sh
python experiments/b/summarize.py experiments/b/results/<run_id>
```

Для перезаписи отчёта по тем же CSV добавьте `--report experiments/b/RESULTS.md`.
`summary.csv` содержит медиану, Q1/Q3, min/max времени и производительность K/T;
`paired_ratios.csv` — все 176 парных отношений table/branch.
Квартили вычисляются линейной интерполяцией в позиции (n−1)p (тип 7).

В `inputs.json` сохраняются рецепты, N, K, SHA-256, распределение видов и доля
пропускаемых байтов. Для исходного учебного текста берётся готовый
`pseudocode/pseudocode.txt`; `run.txt` содержит команду и входом не является.
Для искусственных серий генератор сохраняет ожидаемые виды и границы на основе
рецептов, не используя ни один из измеряемых сканеров. Источник перечисления
TokenKind — общий `scanner.h`.

`environment.json` содержит машину, версии, точные команды компиляции и хеш
бинарного файла. `source_hashes.json` и `source_snapshot.zip` фиксируют исходники.
`dfa_diagnostics.json` объясняет пути контролируемых примеров по общему графу.
