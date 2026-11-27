#!/usr/bin/env python3
"""Извлечь примеры GA и записать их в лексике scanner_spec.txt."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = re.compile(r"\\begin\{(algorithmic|tabbing)\}(.*?)\\end\{\1\}", re.S)
MATH = re.compile(r"(?<!\\)\$\$(.*?)\$\$|(?<!\\)\$((?:\\.|[^$\\])*)\$|\\\[(.*?)\\\]", re.S)
CONTROL = re.compile(r"\\textbf\s*\{\s*(?:if|while|return)\b")
DEF = re.compile(r"\\(?:Def|Assign)\b|:=:")
TOK = re.compile(r"\\[A-Za-z]+|\\[\s\S]|[\s\S]")
FORMAT = set("textbf texttt textit text mathrm mathcal mathbb mathtt mathbf operatorname Bbb frak Bl".split())
OPEN = {"IF": ("if", "then"), "WHILE": ("while", "do"), "FOR": ("for", "do"),
        "FORALL": ("for all", "do"), "REPEAT": ("repeat", "")}
CLOSE = {"ENDIF": "end if", "ENDFOR": "end for", "ENDWHILE": "end while", "UNTIL": "until"}
OTHER = {"STATE": "", "REQUIRE": "require", "ENSURE": "ensure", "ELSE": "else",
         "ELSIF": "else if", "COMMENT": "//"}
STEP = re.compile(r"\\(" + "|".join((*OPEN, *CLOSE, *OTHER)) + r")\b")
SCANNER_TOKEN = re.compile(
    r"[ \t\r\n]+|//[^\r\n]*|[A-Za-z][A-Za-z0-9]*|[0-9]+"
    r"|:=|!=|<=|>=|[=<>+*/()[\],;:\-]"
)

def plain(source, latex_commands):
    tokens = TOK.findall(source)
    i = 0

    def argument():
        nonlocal i
        while i < len(tokens) and tokens[i].isspace():
            i += 1
        if i == len(tokens) or tokens[i] == "}":
            raise ValueError("нет аргумента команды")
        return atom()

    def atom():
        nonlocal i
        token = tokens[i]
        i += 1
        if token == "{":
            parts = []
            while i < len(tokens) and tokens[i] != "}":
                parts.append(atom())
            if i == len(tokens):
                raise ValueError("незакрытая группа TeX")
            i += 1
            return "".join(parts)
        if token == "}":
            raise ValueError("лишняя закрывающая скобка TeX")
        if token in ("_", "^"):
            value = argument()
            if token == "^" and value == "′":
                return value
            return token + (value if len(value) == 1 else "{" + value + "}")
        if not token.startswith("\\"):
            return {"$": "", "~": " "}.get(token, token)
        name = token[1:]
        if name.isalpha():
            while i < len(tokens) and tokens[i].isspace():
                i += 1
        if name == "not" and tokens[i:i+1] == [r"\in"]:
            i += 1
            return "∉"
        if name in FORMAT:
            return argument()
        if name in ("phantom", "color"):
            argument()
            return ""
        if name == "DMref":
            label = argument()
            argument()
            return label
        if name in ("bar", "overline"):
            value = argument()
            return value + "\u0305" if len(value) == 1 else "\\overline{" + value + "}"
        if name == "Set":
            return "{" + argument() + " ∣ " + argument() + "}"
        if name == "stackrel":
            label = argument()
            operator = argument()
            return operator + "[" + label + "]"
        if name in latex_commands:
            return latex_commands[name]
        # Не угадываем смысл авторских макросов. Сохраняем и их аргументы.
        value = token
        while i < len(tokens) and tokens[i] == "{":
            value += "{" + atom() + "}"
        return value + " " if i < len(tokens) and tokens[i][0].isalpha() else value

    parts = []
    while i < len(tokens):
        parts.append(atom())
    return " ".join("".join(parts).split())

def algorithm(body, latex_commands):
    body = re.sub(r"^\s*\[\d+\]", "", body)
    steps = list(STEP.finditer(body))
    if not steps or body[:steps[0].start()].strip():
        raise ValueError("нераспознанное начало algorithmic")
    lines = []
    depth = 0
    for n, step in enumerate(steps):
        name = step[1]
        stop = steps[n+1].start() if n+1 < len(steps) else len(body)
        text = plain(body[step.end():stop], latex_commands)
        if name == "COMMENT":
            if lines:
                lines[-1] += " // " + text
            else:
                lines.append("// " + text)
            continue
        if name in CLOSE or name in ("ELSE", "ELSIF"):
            depth = max(0, depth-1)
        prefix, suffix = OPEN.get(name, (CLOSE.get(name, OTHER.get(name, "")), ""))
        if name == "ELSIF":
            suffix = "then"
        lines.append("    "*depth + " ".join(s for s in (prefix, text, suffix) if s))
        if name in OPEN or name in ("ELSE", "ELSIF"):
            depth += 1
    return "\n".join(lines)

def tabbing(body, latex_commands):
    setup, sep, code = body.partition(r"\kill")
    if not sep or r"\hspace" not in setup:
        return ""
    lines = []
    for row in code.split(r"\\"):
        row = row.strip()
        depth = 0
        while row.startswith(r"\>"):
            depth += 1
            row = row[2:].lstrip()
        if row:
            lines.append("    "*depth + plain(row, latex_commands))
    return "\n".join(lines)

def short(source, latex_commands):
    last = None
    for m in MATH.finditer(source):
        formula = next(v for v in m.groups() if v is not None)
        continued = last is not None and re.fullmatch(r"\s*\\\\\s*", source[last:m.start()])
        if CONTROL.search(formula) and (DEF.search(formula) or continued):
            if not re.search(r"\\(?:begin|end|Prog|frametitle)\b", formula):
                yield m.start(), plain(formula, latex_commands)
                last = m.end()
                continue
        last = None

def extract(path, latex_commands):
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"(?<!\\)((?:\\\\)*)%[^\n]*", r"\1", source)
    pos = 0
    try:
        for m in ENV.finditer(source):
            for _, line in short(source[pos:m.start()], latex_commands):
                yield line
            pos = m.start()
            render = algorithm if m[1] == "algorithmic" else tabbing
            block = render(m[2], latex_commands)
            if block:
                yield block
            pos = m.end()
        for _, line in short(source[pos:], latex_commands):
            yield line
    except ValueError as e:
        raise ValueError(f"{path}, фрагмент около строки {source.count(chr(10),0,pos)+1}: {e}") from e


def normalize(text, patterns, symbols):
    lines = []
    for line in text.split("\n"):
        code, comment_marker, comment = line.partition("//")
        indent = code[:len(code) - len(code.lstrip())]
        for pattern, replacement in patterns:
            code = pattern.sub(replacement, code)
            if "//" in code:
                break
        code, generated_marker, generated_comment = code.partition("//")
        code = "".join(symbols.get(char, char) for char in code)
        code = indent + " ".join(code.split()) if code.strip() else ""
        comments = [part.strip() for part in (generated_comment, comment) if part.strip()]
        if generated_marker or comment_marker:
            code = (code + " " if code else indent) + "// " + " // ".join(comments)
        lines.append(code)
    return "\n".join(lines)


def validate(text):
    pos = 0
    while pos < len(text):
        match = SCANNER_TOKEN.match(text, pos)
        if match is None:
            line = text.count("\n", 0, pos) + 1
            column = pos - text.rfind("\n", 0, pos)
            raise ValueError(
                f"pseudocode.txt:{line}:{column}: недопустимый символ {text[pos]!r}"
            )
        pos = match.end()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", type=Path, help="по умолчанию GA/GA_0…3_2025.tex")
    args = parser.parse_args()
    paths = args.sources or [ROOT.parent/"GA"/f"GA_{i}_2025.tex" for i in range(4)]
    output = ROOT / "pseudocode.txt"
    try:
        table = json.loads((ROOT / "pseudocode_translation.json").read_text(encoding="utf-8"))
        patterns = [(re.compile(pattern), replacement)
                    for pattern, replacement in table["patterns"].items()]
        blocks = [block for path in paths for block in extract(path, table["latex_commands"])]
        if not blocks:
            raise ValueError("не найдено ни одного фрагмента")
        text = normalize("\n\n".join(blocks) + "\n", patterns, table["symbols"])
        validate(text)
        output.write_text(text, encoding="utf-8")
    except (OSError, ValueError) as e:
        parser.exit(1, f"Ошибка: {e}\n")
    print(f"{output.name}: {len(blocks)} фрагментов")

if __name__ == "__main__":
    main()
