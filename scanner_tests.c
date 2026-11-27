#include "table/scanner_table.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

static const struct {
    const char *name;
    const Scanner *scanner;
} scanners[] = {
    {"flex", &scanner_flex},
    {"re2c", &scanner_re2c},
    {"scanner_table", &scanner_table},
    {"scanner_branch", &scanner_branch},
};

typedef struct {
    const char *name;
    const unsigned char *input;
    size_t length;
    const Token *expected;
    size_t count;
} Test;

static int same_token(Token a, Token b)
{
    return a.kind == b.kind && a.begin == b.begin && a.end == b.end;
}

static int check(const char *name, const Scanner *scanner, const Test *test)
{
    void *state = scanner->open(test->input, test->length);
    if (state == NULL) {
        fprintf(stderr, "FAIL %s / %s: open returned NULL\n", name, test->name);
        return 1;
    }

    for (size_t i = 0; i < test->count; ++i) {
        Token got = scanner->next(state);
        Token want = test->expected[i];
        if (!same_token(got, want)) {
            fprintf(stderr, "FAIL %s / %s, token %zu\n"
                    "  expected: kind=%d [%zu, %zu)\n"
                    "  got:      kind=%d [%zu, %zu)\n",
                    name, test->name, i + 1,
                    (int)want.kind, want.begin, want.end,
                    (int)got.kind, got.begin, got.end);
            scanner->close(state);
            return 1;
        }
    }
    scanner->close(state);
    printf("OK %s / %s\n", name, test->name);
    return 0;
}

static int check_examples(void)
{
    static const unsigned char keywords[] = "if if2:=15";
    static const Token words[] = {
        {TOK_IF, 0, 2}, {TOK_IDENT, 3, 6}, {TOK_ASSIGN, 6, 8},
        {TOK_NUMBER, 8, 10}, {TOK_EOF, 10, 10}, {TOK_EOF, 10, 10}
    };

    static const unsigned char comment[] = "x//a\0b\r\n+@";
    static const Token error[] = {
        {TOK_IDENT, 0, 1}, {TOK_PLUS, 8, 9},
        {TOK_ERROR, 9, 10}, {TOK_ERROR, 9, 10}
    };
    static const Token eof[] = {{TOK_EOF, 0, 0}, {TOK_EOF, 0, 0}};
    static const Token only_if[] = {{TOK_IF, 0, 2}, {TOK_EOF, 2, 2}, {TOK_EOF, 2, 2}};
    static const Token only_if2[] = {{TOK_IDENT, 0, 3}, {TOK_EOF, 3, 3}, {TOK_EOF, 3, 3}};
    static const Token assignment[] = {
        {TOK_IF, 0, 2}, {TOK_ASSIGN, 2, 4}, {TOK_NUMBER, 4, 6}, {TOK_EOF, 6, 6}, {TOK_EOF, 6, 6}
    };
    static const unsigned char binary_comment[] = {'/', '/', 0, 0xff};
    static const Token comment_eof[] = {{TOK_EOF, 4, 4}, {TOK_EOF, 4, 4}};
    static const Token invalid[] = {{TOK_ERROR, 0, 1}, {TOK_ERROR, 0, 1}};

    const Test tests[] = {
        {"keywords", keywords, sizeof keywords - 1, words, COUNT(words)},
        {"comment and error", comment, sizeof comment - 1, error, COUNT(error)}
        , {"empty", NULL, 0, eof, COUNT(eof)}
        , {"if", (const unsigned char *)"if", 2, only_if, COUNT(only_if)}
        , {"if2", (const unsigned char *)"if2", 3, only_if2, COUNT(only_if2)}
        , {"if:=15", (const unsigned char *)"if:=15", 6, assignment, COUNT(assignment)}
        , {"binary comment to EOF", binary_comment, sizeof binary_comment, comment_eof, COUNT(comment_eof)}
        , {"unknown byte", (const unsigned char *)"@", 1, invalid, COUNT(invalid)}
    };

    int failures = 0;
    for (size_t i = 0; i < COUNT(tests); ++i) {
        for (size_t j = 0; j < COUNT(scanners); ++j) {
            failures += check(scanners[j].name, scanners[j].scanner, &tests[i]);
        }
    }
    /* Every ordinary TokenKind is checked even if absent from the workload corpus. */
    static const struct { const char *text; TokenKind kind; } spellings[] = {
        {"abc123", TOK_IDENT}, {"0015", TOK_NUMBER},
        {"if", TOK_IF}, {"then", TOK_THEN}, {"else", TOK_ELSE}, {"end", TOK_END},
        {"while", TOK_WHILE}, {"do", TOK_DO}, {"for", TOK_FOR}, {"from", TOK_FROM},
        {"to", TOK_TO}, {"return", TOK_RETURN}, {"case", TOK_CASE},
        {":=", TOK_ASSIGN}, {"=", TOK_EQ}, {"!=", TOK_NE}, {"<", TOK_LT}, {"<=", TOK_LE},
        {">", TOK_GT}, {">=", TOK_GE}, {"+", TOK_PLUS}, {"-", TOK_MINUS}, {"*", TOK_STAR},
        {"/", TOK_SLASH}, {"(", TOK_LPAREN}, {")", TOK_RPAREN}, {"[", TOK_LBRACKET},
        {"]", TOK_RBRACKET}, {",", TOK_COMMA}, {";", TOK_SEMI}, {":", TOK_COLON}
    };
    for (size_t i = 0; i < COUNT(spellings); ++i) {
        size_t length = strlen(spellings[i].text);
        const Token expected[] = {{spellings[i].kind, 0, length},
                                  {TOK_EOF, length, length}, {TOK_EOF, length, length}};
        const Test test = {spellings[i].text, (const unsigned char *)spellings[i].text,
                           length, expected, COUNT(expected)};
        for (size_t j = 0; j < COUNT(scanners); ++j) {
            failures += check(scanners[j].name, scanners[j].scanner, &test);
        }
    }
    printf("Checked %zu ordinary TokenKinds on each of 4 scanners, plus EOF/error cases.\n", COUNT(spellings));
    return failures != 0;
}

static unsigned char *read_text(const char *path, size_t *length)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        perror(path);
        return NULL;
    }

    unsigned char *data = NULL;
    long size = -1;
    if (fseek(file, 0, SEEK_END) == 0) {
        size = ftell(file);
    }
    if (size >= 0 && (uintmax_t)size <= SIZE_MAX && fseek(file, 0, SEEK_SET) == 0) {
        *length = (size_t)size;
        data = malloc(*length == 0 ? 1 : *length);
        if (data != NULL && fread(data, 1, *length, file) != *length) {
            free(data);
            data = NULL;
        }
    }
    fclose(file);
    if (data == NULL) {
        fprintf(stderr, "FAIL %s: could not read input\n", path);
    }
    return data;
}

static int check_text(const char *path)
{
    size_t length;
    unsigned char *data = read_text(path, &length);
    if (data == NULL) {
        return 1;
    }

    size_t opened = 0;
    void *states[COUNT(scanners)];
    for (; opened < COUNT(scanners); ++opened) {
        states[opened] = scanners[opened].scanner->open(data, length);
        if (states[opened] == NULL) {
            fprintf(stderr, "FAIL %s / %s: open returned NULL\n", scanners[opened].name, path);
            break;
        }
    }

    int failed = 1;
    for (size_t i = 0; opened == COUNT(scanners); ++i) {
        Token want = scanners[0].scanner->next(states[0]);
        for (size_t j = 1; j < opened; ++j) {
            Token got = scanners[j].scanner->next(states[j]);
            if (!same_token(got, want)) {
                fprintf(stderr, "FAIL %s / %s, token %zu\n"
                        "  %s: kind=%d [%zu, %zu)\n"
                        "  got: kind=%d [%zu, %zu)\n",
                        scanners[j].name, path, i + 1, scanners[0].name,
                        (int)want.kind, want.begin, want.end,
                        (int)got.kind, got.begin, got.end);
                goto close_scanners;
            }
        }
        if (want.kind == TOK_ERROR) {
            fprintf(stderr, "FAIL %s: lexical error at byte %zu\n", path, want.begin);
            break;
        }
        if (want.kind == TOK_EOF) {
            failed = want.begin != length || want.end != length;
            if (failed) {
                fprintf(stderr, "FAIL %s: EOF [%zu, %zu), expected [%zu, %zu)\n",
                        path, want.begin, want.end, length, length);
            } else {
                printf("OK %s: %zu matching tokens across %zu scanners, EOF at byte %zu\n",
                       path, i, opened, length);
            }
            break;
        }
    }

close_scanners:
    for (size_t j = 0; j < opened; ++j) {
        scanners[j].scanner->close(states[j]);
    }
    free(data);
    return failed;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <input-file>\n", argv[0]);
        return 1;
    }
    int failures = check_examples();
    failures += check_text(argv[1]);
    return failures != 0;
}
