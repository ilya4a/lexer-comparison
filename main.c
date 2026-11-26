#include "scanner.h"
#include <stdio.h>

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

typedef struct {
    const char *name;
    const unsigned char *input;
    size_t length;
    const Token *expected;
    size_t count;
} Test;

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
        if (got.kind != want.kind || got.begin != want.begin || got.end != want.end) {
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

int main(void)
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

    const Test tests[] = {
        {"keywords", keywords, sizeof keywords - 1, words, COUNT(words)},
        {"comment and error", comment, sizeof comment - 1, error, COUNT(error)}
    };

    int failures = 0;
    for (size_t i = 0; i < COUNT(tests); ++i) {
        failures += check("flex", &scanner_flex, &tests[i]);
        failures += check("re2c", &scanner_re2c, &tests[i]);
    }
    return failures != 0;
}
