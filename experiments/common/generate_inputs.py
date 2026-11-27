"""Deterministic workloads shared by A and B, with independent expected tokens."""

import argparse
import hashlib
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
    mib = 1024 * 1024
    specs = [
        ("textbook", "textbook", textbook, 1, 0, "pseudocode/pseudocode.txt"),
        ("prefix_abx", "prefix", b"abx ", mib // 4, 0, "abx only"),
        ("prefix_abx_ifx", "prefix", b"abx ifx ", mib // 8, 0, "alternating abx / ifx"),
        ("prefix_ifx", "prefix", b"ifx ", mib // 4, 0, "ifx only"),
        ("prefix_abcde2", "prefix", b"abcde2 ", mib // 7, 0, "abcde2 only"),
        ("prefix_while2", "prefix", b"while2 ", mib // 7, 0, "while2 only"),
    ]
    for label, byte in (("ident", b"a"), ("number", b"1")):
        for length in (2, 8, 32, 128):
            block = byte * length + b" "
            copies, padding = divmod(mib, len(block))
            specs.append((f"{label}_{length}", "length", block, copies, padding,
                          f"{length} copies of {byte.decode()} and one space per block"))
    spaces = b"x       \n"
    comment = b"x//aaaaa\n"
    long_comment = b"x\n" * 63 + b"x//" + b"a" * (7 * 64 - 2) + b"\n"
    specs.extend([
        ("skip_spaces", "skip", spaces, 131072, 0, "x + seven spaces + LF"),
        ("skip_half", "skip", spaces + comment, 65536, 0, "alternating space and comment blocks"),
        ("skip_comments", "skip", comment, 131072, 0, "x + //aaaaa + LF"),
        ("skip_long_comments", "skip", long_comment, 2048, 0, "one long comment per 64 identifiers"),
    ])
    for copies in (2048, 32768, 524288):
        specs.append((f"mixed_{copies}", "size", b"if x:=15 then return x end if\n", copies,
                      0, "if x:=15 then return x end if + LF"))
    manifest, entries = [], []
    for name, family, block, copies, padding, recipe in specs:
        local = scan_reference(block)
        data_path = destination / f"{name}.bin"
        expected_path = destination / f"{name}.tokens"
        data_path.write_bytes(block * copies + b" " * padding)
        block_size = len(block)
        size = block_size * copies + padding
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
            "copies": copies, "padding": padding, "bytes": size, "tokens": len(local) * copies,
            "sha256": sha256(data_path), "expected_sha256": sha256(expected_path),
            "kind_counts": {kind: count * copies for kind, count in sorted(histogram.items())},
            "skip_byte_fraction": 1 - token_bytes / size,
            "token_lengths": dict(sorted(Counter(end - begin for _, begin, end in local).items()))
                if family == "textbook" else {},
        })
        manifest.append("\t".join((name, family, data_path.resolve().as_posix(),
                                    expected_path.resolve().as_posix(), entries[-1]["sha256"])))
    by_name = {entry["name"]: entry for entry in entries}
    for first, second in (("prefix_abx", "prefix_abx_ifx"), ("prefix_abx", "prefix_ifx"),
                          ("prefix_abcde2", "prefix_while2"), ("skip_spaces", "skip_half"),
                          ("skip_spaces", "skip_comments")):
        if by_name[first]["expected_sha256"] != by_name[second]["expected_sha256"]:
            raise ValueError(f"Control pair differs: {first}, {second}")
    (destination / "manifest.tsv").write_text("\n".join(manifest) + "\n", encoding="utf-8", newline="\n")
    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/inputs/b")
    generate(parser.parse_args().output)
