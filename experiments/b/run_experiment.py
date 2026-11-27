"""Build, verify, run only experiment B, and archive the actual measurements."""

import argparse
import ctypes
import datetime as dt
import importlib.util
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
from generate_inputs import generate, sha256  # noqa: E402
from summarize import report  # noqa: E402


def run(command, log, cwd=ROOT):
    command = [str(part) for part in command]
    print("Running: " + subprocess.list2cmdline(command), flush=True)
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    log.write_text("$ " + subprocess.list2cmdline(command) + "\n" + result.stdout, encoding="utf-8")
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}")
    return result.stdout


def diagnostics():
    path = ROOT / "snirs-dfa/table/generate_dfa.py"
    spec = importlib.util.spec_from_file_location("dfa_description", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names, actions, rows, classes, byte_class = module.build_machine()
    paths = {}
    for text in (b"ifx ", b"abx ", b"aaa ", b"a" * 15 + b" ", b"x       \n", b"x//aaaaa\n"):
        state = names.index("Q_START")
        trace = [names[state]]
        for byte in text:
            following = rows[state][byte_class[byte]]
            if following == 0:
                # These examples never need rollback beyond the last consumed byte.
                state = names.index("Q_START")
                trace.append("[emit/skip; restart]")
                following = rows[state][byte_class[byte]]
            state = following
            trace.append(names[state])
        paths[text.decode("ascii")] = trace
    return {"state_count": len(names), "class_count": len(classes),
            "state_byte_pairs": len(names) * 256, "paths": paths,
            "note": "Traces from the shared DFA description, outside timing; exhaustive equality checked by experiment_b_checks."}


def machine_info():
    cpu = platform.processor()
    memory = 0
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in
                          ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended")]]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        memory = status.total_phys
    elif hasattr(os, "sysconf"):
        memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return {"cpu": cpu, "platform": platform.platform(), "logical_cpus": os.cpu_count(),
            "physical_memory_bytes": memory}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/experiment_b")
    parser.add_argument("--run-id", help="defaults to the current Moscow timestamp")
    args = parser.parse_args()
    started = dt.datetime.now(dt.timezone(dt.timedelta(hours=3), "MSK"))
    run_id = args.run_id or started.strftime("%Y-%m-%d_%H%M%S_MSK")
    if Path(run_id).name != run_id or run_id in (".", ".."):
        parser.error("run-id must be one directory name")
    results = ROOT / "build/results" / run_id
    archive = ROOT / "experiments/b/results" / run_id
    if results.exists() or archive.exists():
        parser.error("run-id already exists; previous results are preserved")
    results.mkdir(parents=True)
    build = args.build_dir.resolve()
    cmake = shutil.which("cmake")
    if not cmake:
        parser.error("cmake is required")
    configure = [cmake, "-S", ROOT, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
                 "-DSNIRS_BUILD_GENERATED_SCANNERS=OFF", "-DCMAKE_C_STANDARD=11",
                 "-DCMAKE_CXX_STANDARD=17", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
    if os.name == "nt":
        cc, cxx = shutil.which("gcc"), shutil.which("g++")
        if not cc or not cxx:
            parser.error("this Windows runner requires MinGW gcc and g++ on PATH")
        configure += ["-G", "MinGW Makefiles", f"-DCMAKE_C_COMPILER={Path(cc).as_posix()}",
                      f"-DCMAKE_CXX_COMPILER={Path(cxx).as_posix()}"]
    else:
        cc, cxx = shutil.which("gcc") or shutil.which("cc"), shutil.which("g++") or shutil.which("c++")
        configure += [f"-DCMAKE_C_COMPILER={cc}", f"-DCMAKE_CXX_COMPILER={cxx}"]
    run(configure, results / "configure.log")
    run([cmake, "--build", build, "--config", "Release", "--target", "experiment_b", "experiment_b_checks",
         "--parallel", "2"], results / "build.log")
    extension = ".exe" if os.name == "nt" else ""
    executable = build / ("experiment_b" + extension)
    checks = build / ("experiment_b_checks" + extension)
    run([checks], results / "correctness.log")
    run([sys.executable, ROOT / "snirs-dfa/table/generate_dfa.py", "--check"], results / "generation.log")
    inputs_dir = ROOT / "build/inputs/b"
    generate(inputs_dir)
    shutil.copy2(inputs_dir / "manifest.json", results / "inputs.json")
    shutil.copy2(inputs_dir / "manifest.tsv", results / "manifest.tsv")
    (results / "dfa_diagnostics.json").write_text(json.dumps(diagnostics(), indent=2) + "\n", encoding="utf-8")
    metadata = machine_info()
    metadata.update({"run_id": run_id, "started_moscow": started.isoformat(),
        "c_version": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
        "cxx_version": subprocess.check_output([cxx, "--version"], text=True).splitlines()[0],
        "cmake_version": subprocess.check_output([cmake, "--version"], text=True).splitlines()[0],
        "python": sys.version, "configure_command": [str(x) for x in configure],
        "rounds": 16, "warmups_per_variant_per_input": 1, "affinity": "not pinned",
        "priority": "normal", "executable_sha256": sha256(executable),
        "git_commit": subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "compile_commands": json.loads((build / "compile_commands.json").read_text(encoding="utf-8")),
        "guide_schema_note": "experiment_results.txt is not present; CSV fields are documented in experiments/b/README.md"})
    # Save all source bytes needed to reproduce this build and these inputs.
    sources = [ROOT / name for name in ("CMakeLists.txt", "build.sh", "scanner.h", "spec/scanner_spec.txt",
        "spec/SNIRS_plan.tex", "experiment_b_guide.txt", "pseudocode/pseudocode.txt",
        "pseudocode/pseudocode_translation.json", "pseudocode/run.txt")]
    for folder in ("snirs-dfa/table", "snirs-dfa/tests", "experiments/common"):
        sources += [p for p in (ROOT / folder).iterdir() if p.is_file()]
    sources += [ROOT / "snirs-dfa/CMakeLists.txt", ROOT / "experiments/b/experiment_b.c",
                Path(__file__).resolve(), ROOT / "experiments/b/summarize.py"]
    source_hashes = {path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(set(sources))}
    with zipfile.ZipFile(results / "source_snapshot.zip", "w", zipfile.ZIP_DEFLATED) as snapshot:
        for path in sorted(set(sources)):
            snapshot.write(path, path.relative_to(ROOT).as_posix())
    (results / "source_hashes.json").write_text(json.dumps(source_hashes, indent=2) + "\n", encoding="utf-8")
    # No further compilation, generation, or validation shares a timed interval.
    run([executable, inputs_dir / "manifest.tsv", results / "samples.csv", results / "validation.csv"], results / "benchmark.log")
    metadata["finished_moscow"] = dt.datetime.now(started.tzinfo).isoformat()
    (results / "environment.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report(results, results / "REPORT.md")
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(results, archive)
    shutil.copy2(results / "REPORT.md", ROOT / "experiments/b/RESULTS.md")
    print(f"Archived {archive.relative_to(ROOT)}; report: experiments/b/RESULTS.md", flush=True)


if __name__ == "__main__":
    main()
