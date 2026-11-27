"""Deterministic experiment-B corpus and independent, exact expected token streams."""

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN = re.compile(rb"[ \t\r\n]+|//[^\r\n]*|[A-Za-z][A-Za-z0-9]*|[0-9]+|:=|!=|<=|>=|[=<>+*/()[\],;:\-]")
WORDS = dict(zip(
    (b"if", b"then", b"else", b"end", b"while", b"do", b"for", b"from", b"to", b"return", b"case"),
    ("TOK_IF", "TOK_THEN", "TOK_ELSE", "TOK_END", "TOK_WHILE", "TOK_DO", "TOK_FOR", "TOK_FROM", "TOK_TO", "TOK_RETURN", "TOK_CASE")))
SIGNS = dict(zip(
    (b":=", b"=", b"!=", b"<", b"<=", b">", b">=", b"+", b"-", b"*", b"/", b"(", b")", b"[", b"]", b",", b";", b":"),
    ("TOK_ASSIGN", "TOK_EQ", "TOK_NE", "TOK_LT", "TOK_LE", "TOK_GT", "TOK_GE", "TOK_PLUS", "TOK_MINUS", "TOK_STAR", "TOK_SLASH", "TOK_LPAREN", "TOK_RPAREN", "TOK_LBRACKET", "TOK_RBRACKET", "TOK_COMMA", "TOK_SEMI", "TOK_COLON")))
RECORD = struct.Struct("<IQQ")


def token_ids():
    # Read the common enum, independently of the DFA's state labels.
    header = (ROOT / "scanner.h").read_text(encoding="utf-8")
    names = re.findall(r"\bTOK_[A-Z_]+\b", header.split("} TokenKind;")[0])
    assert len(names) == len(set(names))
    return {name: i for i, name in enumerate(names)}


def scan_reference(data):
    result = []
    position = 0
    while position < len(data):
        match = TOKEN.match(data, position)
        if match is None:
            raise ValueError(f"Invalid byte {data[position]:02x} at {position}")
        word = match.group()
        begin, position = position, match.end()
        if word.startswith(b"//") or word[0] in b" \t\r\n":
            continue
        if word in WORDS:
            kind = WORDS[word]
        elif 65 <= word[0] <= 90 or 97 <= word[0] <= 122:
            kind = "TOK_IDENT"
        elif 48 <= word[0] <= 57:
            kind = "TOK_NUMBER"
        else:
            kind = SIGNS[word]
        result.append((kind, begin, position))
    return result


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    ids = token_ids()
    textbook = (ROOT / "pseudocode/pseudocode.txt").read_bytes()
    # run.txt is a command, not scanner input. Preserve the already translated material.
    specs = [
        ("textbook", "textbook", textbook, 1, "pseudocode/pseudocode.txt, unchanged"),
        ("textbook_long", "textbook", textbook + b"\n", (1048576 + len(textbook)) // (len(textbook) + 1), "whole copies of textbook, with one extra LF per copy"),
        ("prefix_ifx", "I_prefix", b"ifx ", 262144, "b'ifx ' * 262144"),
        ("prefix_abx", "I_prefix", b"abx ", 262144, "b'abx ' * 262144"),
        ("ident_3", "II_length", b"aaa ", 262144, "b'aaa ' * 262144"),
        ("ident_15", "II_length", b"a" * 15 + b" ", 65536, "(b'a'*15 + b' ') * 65536"),
        ("skip_spaces", "III_skip", b"x       \n", 131072, "b'x       \\n' * 131072"),
        ("skip_comments", "III_skip", b"x//aaaaa\n", 131072, "b'x//aaaaa\\n' * 131072"),
    ]
    for copies in (2048, 32768, 524288):
        specs.append((f"mixed_{copies}", "IV_size", b"if x:=15 then return x end if\n", copies,
                      f"b'if x:=15 then return x end if\\n' * {copies}"))
    manifest, entries = [], []
    for name, family, block, copies, recipe in specs:
        local = scan_reference(block)
        data_path = destination / f"{name}.bin"
        expected_path = destination / f"{name}.tokens"
        data_path.write_bytes(block * copies)
        block_size = len(block)
        size = block_size * copies
        with expected_path.open("wb") as expected:
            buffer = bytearray()
            for i in range(copies):
                offset = block_size * i
                for kind, begin, end in local:
                    buffer.extend(RECORD.pack(ids[kind], offset + begin, offset + end))
                if len(buffer) > 1024 * 1024:
                    expected.write(buffer)
                    buffer.clear()
            buffer.extend(RECORD.pack(ids["TOK_EOF"], size, size))
            expected.write(buffer)
        histogram = Counter(kind for kind, _, _ in local)
        token_bytes = sum(end - begin for _, begin, end in local) * copies
        entries.append({
            "name": name, "family": family, "recipe": recipe, "block_bytes": block_size,
            "copies": copies, "bytes": size, "tokens": len(local) * copies,
            "lines": (block.count(b"\n") * copies + (not block.endswith(b"\n"))),
            "sha256": sha256(data_path), "expected_sha256": sha256(expected_path),
            "kind_counts": {kind: count * copies for kind, count in sorted(histogram.items())},
            "skip_byte_fraction": 1 - token_bytes / size,
            "source": "pseudocode/pseudocode.txt" if family == "textbook" else "experiment_b_guide.txt section 6",
        })
        manifest.append("\t".join((name, family, data_path.resolve().as_posix(), expected_path.resolve().as_posix())))
        print(f"Prepared {name}: {size} bytes, {len(local) * copies} tokens", flush=True)
    # In the controlled pairs the complete lexical result, including EOF, is identical.
    by_name = {entry["name"]: entry for entry in entries}
    for first, second in (("prefix_ifx", "prefix_abx"), ("skip_spaces", "skip_comments")):
        assert by_name[first]["expected_sha256"] == by_name[second]["expected_sha256"]
    (destination / "manifest.tsv").write_text("\n".join(manifest) + "\n", encoding="utf-8", newline="\n")
    (destination / "manifest.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/inputs/b")
    generate(parser.parse_args().output)
