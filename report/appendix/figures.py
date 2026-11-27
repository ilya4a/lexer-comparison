"""Rebuild both figures, LaTeX tables and the paired summary from the raw series."""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = Path(__file__).resolve().parent
DATA = HERE / "results"
FIG = HERE.parent / "figures"
TABLE = HERE.parent / "tables"
VAR = ("flex", "re2c", "table", "branch")
NAMES = {
    "textbook": "Учебный корпус", "prefix_abx": "abx", "prefix_abx_ifx": "abx / ifx",
    "prefix_ifx": "ifx", "prefix_abcde2": "abcde2", "prefix_while2": "while2",
    "skip_spaces": "Пробелы", "skip_half": "Через строку", "skip_comments": "Короткие комм.",
    "skip_long_comments": "Длинные комм.", "mixed_2048": "Смесь × 2 048",
    "mixed_32768": "Смесь × 32 768", "mixed_524288": "Смесь × 524 288",
}
for n in (2, 8, 32, 128):
    NAMES[f"ident_{n}"] = f"Буквы, {n}"
    NAMES[f"number_{n}"] = f"Цифры, {n}"

def interval(values):
    q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return median, q1, q3

def dec(value, places=3):
    return f"{value:.{places}f}".replace(".", ",")

def integer(value):
    return f"{value:,}".replace(",", r"\,")

def load_series():
    entries = json.loads((DATA / "inputs.json").read_text("utf-8"))
    meta = {e["name"]: e for e in entries}
    samples = defaultdict(dict)
    raw = []
    with (DATA / "measurements.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name, variant, r = row["input_id"], row["variant"], int(row["round"])
            key = (name, variant)
            e = meta[name]
            size, passes = int(row["bytes"]), int(row["passes"])
            assert 1 <= r <= 16 and r not in samples[key]
            assert int(row["order"]) == (VAR.index(variant) - r + 1) % 4 + 1
            assert size == e["bytes"] and int(row["tokens"]) == e["tokens"]
            assert passes == (16 if size < 65536 else 1) and e["sha256"] == row["input_sha256"]
            samples[key][r] = float(row["elapsed_ns"]) / passes / size
            record = dict(row)
            for field in ("round", "order", "bytes", "tokens", "passes"):
                record[field] = int(row[field])
            record["elapsed_ns"] = float(row["elapsed_ns"])
            raw.append(record)
    assert len(samples) == len(entries) * 4 and all(len(x) == 16 for x in samples.values())
    (DATA / "measurements.jsonl").write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in raw),
        "utf-8", newline="\n")
    return entries, samples

def main():
    FIG.mkdir(exist_ok=True)
    TABLE.mkdir(exist_ok=True)
    entries, samples = load_series()
    summary = {}
    rows_a, rows_b = [], []
    previous = None
    for e in entries:
        name = e["name"]
        by_variant = {v: interval(samples[name,v].values()) for v in VAR}
        ratios = [samples[name,"table"][r] / samples[name,"branch"][r] for r in range(1,17)]
        m, lo, hi = interval(ratios)
        wins = sum(x > 1 for x in ratios)
        if previous and e["family"] != previous:
            rows_a.append(r"\addlinespace[2pt]")
            rows_b.append(r"\midrule")
        previous = e["family"]
        cells = []
        for v in VAR:
            t, q1, q3 = by_variant[v]
            cells.append(r"\timecell{%s}{%s}{%s}" % (dec(t),dec(q1),dec(q3)))
        rows_a.append(" & ".join([NAMES[name],integer(e["bytes"]),integer(e["tokens"]),*cells]) + r" \\")
        rows_b.append(" & ".join([NAMES[name], dec(m), dec(lo), dec(hi), str(wins)]) + r" \\")
        summary[name] = {"ns_per_byte": by_variant, "ratio": [m,lo,hi], "branch_wins": wins}
    for suffix, rows in (("a",rows_a),("b",rows_b)):
        (TABLE / f"{suffix}.tex").write_text("\n".join(rows)+"\n","utf-8")
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2)+"\n","utf-8")
    report_file = DATA / "REPORT.md"
    report = report_file.read_text("utf-8").split("\n## Опыт Б")[0].rstrip()
    paired = ["", "## Опыт Б", "",
              "Те же четыре запуска в каждом раунде. Для Б взяты table и branch. "
              "R равно времени table, делённому на время branch в том же раунде.", "",
              "| Вход | Медиана R | Q1 | Q3 | Побед branch из 16 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for name, stats in summary.items():
        paired.append("| " + " | ".join([name, *(dec(x) for x in stats["ratio"]),
                                         str(stats["branch_wins"])]) + " |")
    report_file.write_text(report + "\n" + "\n".join(paired) + "\n", "utf-8")
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,
                         "axes.spines.right":False,"pdf.fonttype":42, "axes.axisbelow":True})
    fig, axes = plt.subplots(1,2,figsize=(7.1,3.4),sharey=True)
    for ax,family,title in zip(axes,("ident","number"),("Идентификаторы","Числа")):
        for i,(v,mk,color) in enumerate(zip(VAR,("o","s","^","D"),("#4c4c4c","#006f76","#9c471a","#4e5794"))):
            x = [n * 4 ** ((i-1.5)*.045) for n in (2,8,32,128)]
            vals = [summary[f"{family}_{n}"]["ns_per_byte"][v] for n in (2,8,32,128)]
            y,lo,hi = zip(*vals)
            ax.errorbar(x,y,yerr=([a-b for a,b in zip(y,lo)],[b-a for a,b in zip(y,hi)]),
                        label=v,fmt=mk+"-",color=color,linewidth=1.15,markersize=4,capsize=2)
        ax.set_xscale("log", base=4)
        ax.set_xticks([2,8,32,128],labels=["2","8","32","128"])
        ax.minorticks_off()
        ax.set_xlabel("Длина лексемы, байт")
        ax.set_title(title,fontsize=10)
        ax.grid(axis="y",alpha=.20)
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel("Время, нс/байт")
    axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{v:g}".replace(".",",")))
    fig.legend(*axes[0].get_legend_handles_labels(),loc="lower center",ncols=4,frameon=False)
    fig.subplots_adjust(left=.095,right=.985,top=.89,bottom=.28,wspace=.10)
    fig.savefig(FIG / "length.pdf")
    plt.close(fig)

    names = ["textbook","prefix_abx","prefix_ifx","ident_2","ident_8","ident_128",
             "number_2","number_128","skip_spaces","skip_long_comments","mixed_2048","mixed_524288"]
    fig,ax=plt.subplots(figsize=(7.1,4.0))
    for i,name in enumerate(names):
        m,lo,hi = summary[name]["ratio"]
        ax.errorbar(m,i,xerr=[[m-lo],[hi-m]],fmt="o",color="#174c62",capsize=3,markersize=4)
    ax.axvline(1,color="black",linestyle="--",linewidth=.9)
    ax.set_yticks(range(len(names)),labels=[NAMES[n] for n in names])
    ax.invert_yaxis()
    ax.grid(axis="x",alpha=.22)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x,_: f"{x:g}".replace(".",",")))
    ax.set_xlabel("Отношение времени table / branch, безразмерное")
    fig.subplots_adjust(left=.23,right=.97,top=.96,bottom=.16)
    fig.savefig(FIG / "ratios.pdf")
    plt.close(fig)

if __name__ == "__main__":
    main()
