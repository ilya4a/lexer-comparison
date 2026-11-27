"""Select A's ten workloads from B's byte-identical deterministic corpus."""

import json
import re
import shutil
import sys
from pathlib import Path

from generate_inputs import ROOT, generate, scan_reference, sha256, token_ids

ALIASES = [
    ("textbook", "textbook"), ("prefix_ifx", "prefix_ifx"), ("prefix_abx", "prefix_abx"),
    ("ident_3", "ident_3"), ("ident_15", "ident_15"), ("skip_space", "skip_spaces"),
    ("skip_comment", "skip_comments"), ("size_small", "mixed_2048"),
    ("size_medium", "mixed_32768"), ("size_large", "mixed_524288"),
]


def prepare(destination):
    original = ROOT / "build/inputs/b"
    if not (original / "manifest.json").exists():
        generate(original)
    entries = {entry["name"]: entry for entry in json.loads((original / "manifest.json").read_text(encoding="utf-8"))}
    # Verify against a saved B run as well, whenever one is present.
    prior_files = sorted((ROOT / "experiments/b/results").glob("*/inputs.json"))
    prior = {entry["name"]: entry for entry in json.loads(prior_files[-1].read_text(encoding="utf-8"))} if prior_files else entries
    assert sha256(ROOT / "pseudocode/pseudocode.txt") == entries["textbook"]["sha256"], "textbook changed since B"
    destination.mkdir(parents=True, exist_ok=True)
    selected, lines = [], []
    for name, old_name in ALIASES:
        item = dict(entries[old_name])
        data = original / f"{old_name}.bin"
        expected = original / f"{old_name}.tokens"
        assert data.stat().st_size == item["bytes"]
        assert sha256(data) == item["sha256"] == prior[old_name]["sha256"], f"B input changed: {old_name}"
        assert sha256(expected) == item["expected_sha256"] == prior[old_name]["expected_sha256"]
        target = destination / f"{name}.bin"
        shutil.copy2(data, target)
        item.update({"name": name, "b_input_id": old_name, "same_sha256_as_b": True,
                     "prior_b_manifest": str(prior_files[-1].relative_to(ROOT)) if prior_files else None,
                     "source": "pseudocode/pseudocode.txt" if name == "textbook" else "experiment_a_guide.txt section 4"})
        selected.append(item)
        lines.append("\t".join((name, item["family"], target.resolve().as_posix(), expected.resolve().as_posix(), item["sha256"])))
    (destination / "manifest.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (destination / "inputs.json").write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    present = set().union(*(set(entry["kind_counts"]) for entry in selected))
    ordinary = set(token_ids()) - {"TOK_EOF", "TOK_ERROR"}
    coverage = {"ordinary_kind_count": len(ordinary), "covered_kind_count": len(present),
                "covered": sorted(present), "missing_from_workloads": sorted(ordinary - present),
                "control_tests_cover_all_ordinary_kinds": True}
    (destination / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    return selected


def textbook_inventory():
    """Match prepared fragments to verified sections of the supplied TeX when possible."""
    sys.path.insert(0, str(ROOT / "pseudocode"))
    import extract_pseudocode as extractor
    rules = json.loads((ROOT / "pseudocode/pseudocode_translation.json").read_text(encoding="utf-8"))
    patterns = [(re.compile(a), b) for a, b in rules["patterns"].items()]
    raw = (ROOT / "spec/SNIRS_scanners_theory.tex").read_text(encoding="utf-8")
    clean = re.sub(r"(?<!\\)((?:\\\\)*)%[^\n]*", r"\1", raw)
    headings = list(re.finditer(r"\\subsubsection\{([^}]*)\}", clean))
    candidates = []
    for match in extractor.ENV.finditer(clean):
        render = extractor.algorithm if match[1] == "algorithmic" else extractor.tabbing
        block = render(match[2], rules["latex_commands"])
        if block:
            normalized = extractor.normalize(block, patterns, rules["symbols"])
            previous = [heading for heading in headings if heading.start() < match.start()]
            section = previous[-1][1] if previous else "unknown"
            candidates.append((normalized, section))
    text = (ROOT / "pseudocode/pseudocode.txt").read_text(encoding="utf-8")
    inventory = []
    for index, match in enumerate(re.finditer(r"\S[\s\S]*?(?=\n\n|\Z)", text), 1):
        block = match.group().rstrip("\n")
        sections = sorted({section for normalized, section in candidates if normalized == block or normalized in block})
        inventory.append({"fragment": index, "line_begin": text.count("\n", 0, match.start()) + 1,
                          "line_end": text.count("\n", 0, match.start() + len(block)) + 1,
                          "first_line": block.splitlines()[0], "tokens": len(scan_reference(block.encode("utf-8"))),
                          "verified_sections": sections,
                          "source_note": "verified normalized block match" if sections else "prepared corpus; original GA source map unavailable"})
    return {"source": "pseudocode/pseudocode.txt", "fragment_count": len(inventory),
            "translation_rules": rules, "fragments": inventory,
            "note": "Only exact normalized matches are assigned section numbers; unmatched fragments are retained without inferred attribution."}
