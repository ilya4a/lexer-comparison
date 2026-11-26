/* Deliberately include the unchanged common contract from a C11 module. */
#include "scanner.h"

int main(void) {
    static const unsigned char input[] = {'i', 'f', ':', '=', '1', '5'};
    const Token expected[] = {
        {TOK_IF, 0, 2}, {TOK_ASSIGN, 2, 4}, {TOK_NUMBER, 4, 6}, {TOK_EOF, 6, 6}
    };
    void *state = scanner_table.open(input, sizeof input);
    size_t i;
    if (!state) return 1;
    for (i = 0; i < sizeof expected / sizeof expected[0]; ++i) {
        const Token actual = scanner_table.next(state);
        if (actual.kind != expected[i].kind || actual.begin != expected[i].begin ||
            actual.end != expected[i].end) {
            scanner_table.close(state);
            return 2;
        }
    }
    scanner_table.close(state);
    return 0;
}
