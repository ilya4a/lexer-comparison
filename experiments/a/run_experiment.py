"""Run experiment A: all four scanners, ten fixed files, 16 balanced rounds."""

import argparse
import ctypes
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/common"))
from generate_inputs import sha256
from prepare_a import prepare, textbook_inventory
from summarize import ORDERS, write_report


def execute(command, log):
    command = list(map(str, command))
    print("Running: " + subprocess.list2cmdline(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_text("$ " + subprocess.list2cmdline(command) + "\n" + result.stdout, encoding="utf-8")
    lines = result.stdout.splitlines()
    print("\n".join(lines if len(lines) <= 25 else lines[-12:]), flush=True)
    if result.returncode:
        raise RuntimeError(f"Exit {result.returncode}; see {log}")
    return result.stdout


def system_info():
    cpu = platform.processor()
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in ("physical", "available", "page", "free_page", "virtual", "free_virtual", "extended")]]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise OSError("GlobalMemoryStatusEx failed")
        size = memory.physical
    else:
        size = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return {"cpu": cpu, "logical_cpus": os.cpu_count(), "physical_memory_bytes": size, "platform": platform.platform()}


def tool(explicit, command, fallback):
    value = explicit or shutil.which(command) or (str(fallback) if fallback.is_file() else None)
    if not value:
        raise RuntimeError(f"{command} not found; provide its path as a command-line option")
    return str(Path(value).resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flex")
    parser.add_argument("--re2c")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/experiment_a")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    started = dt.datetime.now(dt.timezone(dt.timedelta(hours=3), "MSK"))
    run_id = args.run_id or started.strftime("%Y-%m-%d_%H%M%S_A_MSK")
    if Path(run_id).name != run_id or run_id in (".", ".."):
        parser.error("run-id must be a single directory name")
    results = ROOT / "build/results" / run_id
    archive = ROOT / "experiments/a/results" / run_id
    if results.exists() or archive.exists():
        parser.error("run-id already exists")
    flex = tool(args.flex, "flex", ROOT / "build/tools/winflexbison/win_flex.exe")
    re2c = tool(args.re2c, "re2c", ROOT / "build/tools/re2c-build/re2c.exe")
    cmake, cc, cxx = shutil.which("cmake"), shutil.which("gcc"), shutil.which("g++")
    if not all((cmake, cc, cxx)):
        parser.error("cmake, gcc and g++ are required")
    results.mkdir(parents=True)
    (results / "run.txt").write_text("status=PREPARING\nexperiment=A\n", encoding="utf-8")
    try:
        build = args.build_dir.resolve()
        configure = [cmake, "-S", ROOT, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
                     "-DSNIRS_BUILD_GENERATED_SCANNERS=ON", "-DCMAKE_C_STANDARD=11", "-DCMAKE_CXX_STANDARD=17",
                     "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", f"-DFLEX_EXECUTABLE={Path(flex).as_posix()}",
                     f"-DRE2C_EXECUTABLE={Path(re2c).as_posix()}", f"-DCMAKE_C_COMPILER={Path(cc).as_posix()}",
                     f"-DCMAKE_CXX_COMPILER={Path(cxx).as_posix()}"]
        if os.name == "nt":
            configure += ["-G", "MinGW Makefiles"]
        execute(configure, results / "configure.log")
        execute([cmake, "--build", build, "--config", "Release", "--target", "experiment_a", "scanner_tests",
                 "experiment_b_checks", "--parallel", "2"], results / "build.log")
        extension = ".exe" if os.name == "nt" else ""
        executable = build / ("experiment_a" + extension)
        execute([build / ("scanner_tests" + extension), ROOT / "pseudocode/pseudocode.txt"], results / "control_tests.log")
        execute([build / ("experiment_b_checks" + extension)], results / "dfa_checks.log")
        execute([sys.executable, ROOT / "snirs-dfa/table/generate_dfa.py", "--check"], results / "generation.log")
        inputs_dir = ROOT / "build/inputs/a"
        inputs = prepare(inputs_dir)
        for name in ("inputs.json", "coverage.json", "manifest.tsv"):
            shutil.copy2(inputs_dir / name, results / name)
        (results / "textbook_inventory.json").write_text(json.dumps(textbook_inventory(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Complete all-file preflight before recording any performance results.
        execute([executable, "--validate-only", inputs_dir / "manifest.tsv", results / "preflight_empty.csv",
                 results / "preflight_validation.csv"], results / "preflight.log")
        environment = system_info()
        version = lambda path: subprocess.check_output([path, "--version"], text=True).splitlines()[0]
        environment.update({"experiment": "A", "started_moscow": started.isoformat(), "run_id": run_id,
            "c_version": version(cc), "cxx_version": version(cxx), "flex_version": version(flex),
            "re2c_version": version(re2c), "cmake_version": version(cmake), "python": sys.version,
            "git_commit": subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "configure_command": list(map(str, configure)), "rounds": 16, "warmups": 1, "orders": ORDERS,
            "compile_commands": json.loads((build / "compile_commands.json").read_text(encoding="utf-8")),
            "generator_commands": [f"{flex} -8 -Cf -o scanner_flex.c flex/scanner.l", f"{re2c} -o scanner_re2c.c re2c/scanner.re"],
            "generator_sha256": {"flex": sha256(Path(flex)), "re2c": sha256(Path(re2c))},
            "executable_sha256": sha256(executable), "textbook_copies": 1,
            "checksum": "uint64, initial=14695981039346656037; each Token including EOF: XOR kind, multiply 1099511628211, XOR begin, multiply, XOR end, multiply; mod 2^64; K excludes EOF",
            "tool_downloads": [{"url": url, "sha256": sha256(ROOT / filename)} for url, filename in (
                ("https://github.com/lexxmark/winflexbison/releases/download/v2.5.25/win_flex_bison-2.5.25.zip", "build/tools/win_flex_bison-2.5.25.zip"),
                ("https://github.com/skvadrik/re2c/releases/download/4.6/re2c-4.6.tar.xz", "build/tools/re2c-4.6.tar.xz")) if (ROOT / filename).exists()]})
        source_files = [ROOT / name for name in ("CMakeLists.txt", "build.sh", "scanner.h", "scanner_tests.c",
            "experiment_a_guide.txt", "experiment_results.txt", "spec/scanner_spec.txt", "spec/SNIRS_scanners_theory.tex",
            "snirs-dfa/CMakeLists.txt", "pseudocode/pseudocode.txt", "pseudocode/run.txt",
            "pseudocode/pseudocode_translation.json", "pseudocode/extract_pseudocode.py")]
        for directory in (ROOT / "experiments/a", ROOT / "experiments/common", ROOT / "snirs-dfa/table", ROOT / "snirs-dfa/tests", build / "generated"):
            source_files += [path for path in directory.iterdir() if path.is_file() and path.suffix in (".py", ".c", ".cpp", ".h", ".tsv", ".dot")]
        source_files += [ROOT / "flex/scanner.l", ROOT / "re2c/scanner.re"]
        hashes = {path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(set(source_files))}
        (results / "source_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(results / "source_snapshot.zip", "w", zipfile.ZIP_DEFLATED) as snapshot:
            for path in sorted(set(source_files)):
                snapshot.write(path, path.relative_to(ROOT).as_posix())
        command = [executable, inputs_dir / "manifest.tsv", results / "measurements.csv", results / "validation.csv"]
        run_text = ["status=MEASURING", "experiment=A", f"date_moscow={started.isoformat()}",
                    "variants=flex,re2c,table,branch", "clock=QueryPerformanceCounter (Windows); CLOCK_MONOTONIC (POSIX)",
                    "warmups_per_variant_per_input=1", "rounds=16", "priority=normal; affinity=not pinned",
                    "timed=next loop, K, checksum; excluded=open,close,copying,input I/O,validation,CSV",
                    "format=experiment_results.txt, A variant list amended per experiment_a_guide.txt",
                    "quartiles=linear interpolation at (n-1)*p", "checksum=" + environment["checksum"],
                    "command=" + subprocess.list2cmdline(list(map(str, command))),
                    "configure=" + subprocess.list2cmdline(list(map(str, configure)))]
        run_text += [f"{key}={environment[key]}" for key in ("git_commit", "cpu", "platform", "logical_cpus", "physical_memory_bytes", "c_version", "cxx_version", "flex_version", "re2c_version", "executable_sha256")]
        run_text += [f"order_{i+1}=" + ",".join(order) for i, order in enumerate(ORDERS)]
        run_text += ["generation=" + command for command in environment["generator_commands"]]
        run_text += ["compile=" + item["command"] for item in environment["compile_commands"]]
        run_text += [f"input={item['name']}; source_in_b={item['b_input_id']}; N={item['bytes']}; K={item['tokens']}; copies={item['copies']}; SHA256={item['sha256']}; recipe={item['recipe']}" for item in inputs]
        (results / "run.txt").write_text("\n".join(run_text) + "\n", encoding="utf-8")
        log = execute(command, results / "benchmark.log")
        environment["finished_moscow"] = dt.datetime.now(started.tzinfo).isoformat()
        (results / "environment.json").write_text(json.dumps(environment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_report(results, results / "REPORT.md")
        run_text[0] = "status=COMPLETE"
        run_text += ["timer=" + log.splitlines()[0], "summary_rows=40; measurement_rows=640; errors=0"]
        (results / "run.txt").write_text("\n".join(run_text) + "\n", encoding="utf-8")
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(results, archive)
        shutil.copy2(results / "REPORT.md", ROOT / "experiments/a/RESULTS.md")
        print(f"Completed: {archive.relative_to(ROOT)}", flush=True)
    except Exception as error:
        with (results / "run.txt").open("a", encoding="utf-8") as stream:
            stream.write(f"\nstatus=ABORTED\nreason={error}\n")
        raise


if __name__ == "__main__":
    main()
