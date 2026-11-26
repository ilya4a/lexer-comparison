/* Генерация из корня проекта: re2c -o build/scanner_re2c.c re2c/scanner.re */
#include "scanner.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const unsigned char *cursor;
    const unsigned char *limit;
    int finished;
    Token last;
    unsigned char input[];
} Re2cState;

static void *re2c_open(const unsigned char *data, size_t length)
{
    if ((!data && length != 0) || length > PTRDIFF_MAX ||
        length > SIZE_MAX - sizeof(Re2cState) - 1)
        return NULL;

    Re2cState *s = malloc(sizeof *s + length + 1);
    if (!s)
        return NULL;
    if (length != 0)
        memcpy(s->input, data, length);

    /* Служебный байт. Настоящий 0x00 внутри текста отличается по позиции. */
    s->input[length] = 0;
    s->cursor = s->input;
    s->limit = s->input + length;
    s->finished = 0;
    return s;
}

static Token re2c_next(void *state)
{
    Re2cState *s = state;
    if (s->finished)
        return s->last;

    const unsigned char *YYCURSOR = s->cursor;
    const unsigned char *YYLIMIT = s->limit;
    const unsigned char *YYMARKER = YYCURSOR;
    (void)YYMARKER; /* Использование зависит от оптимизаций генератора. */
    const unsigned char *start;
    TokenKind kind;

    for (;;) {
        start = YYCURSOR;
        /*!re2c
            re2c:define:YYCTYPE = "unsigned char";
            re2c:yyfill:enable = 0;
            re2c:eof = 0;

            id      = [A-Za-z][A-Za-z0-9]*;
            number  = [0-9]+;
            space   = [ \t\r\n]+;
            comment = "//" [^\r\n]*;

            "if"      { kind = TOK_IF; goto token_ready; }
            "then"    { kind = TOK_THEN; goto token_ready; }
            "else"    { kind = TOK_ELSE; goto token_ready; }
            "end"     { kind = TOK_END; goto token_ready; }
            "while"   { kind = TOK_WHILE; goto token_ready; }
            "do"      { kind = TOK_DO; goto token_ready; }
            "for"     { kind = TOK_FOR; goto token_ready; }
            "from"    { kind = TOK_FROM; goto token_ready; }
            "to"      { kind = TOK_TO; goto token_ready; }
            "return"  { kind = TOK_RETURN; goto token_ready; }
            "case"    { kind = TOK_CASE; goto token_ready; }

            id        { kind = TOK_IDENT; goto token_ready; }
            number    { kind = TOK_NUMBER; goto token_ready; }
            ":="      { kind = TOK_ASSIGN; goto token_ready; }
            "="       { kind = TOK_EQ; goto token_ready; }
            "!="      { kind = TOK_NE; goto token_ready; }
            "<"       { kind = TOK_LT; goto token_ready; }
            "<="      { kind = TOK_LE; goto token_ready; }
            ">"       { kind = TOK_GT; goto token_ready; }
            ">="      { kind = TOK_GE; goto token_ready; }
            "+"       { kind = TOK_PLUS; goto token_ready; }
            "-"       { kind = TOK_MINUS; goto token_ready; }
            "*"       { kind = TOK_STAR; goto token_ready; }
            "/"       { kind = TOK_SLASH; goto token_ready; }
            "("       { kind = TOK_LPAREN; goto token_ready; }
            ")"       { kind = TOK_RPAREN; goto token_ready; }
            "["       { kind = TOK_LBRACKET; goto token_ready; }
            "]"       { kind = TOK_RBRACKET; goto token_ready; }
            ","       { kind = TOK_COMMA; goto token_ready; }
            ";"       { kind = TOK_SEMI; goto token_ready; }
            ":"       { kind = TOK_COLON; goto token_ready; }

            space     { continue; }
            comment   { continue; }
            $         { kind = TOK_EOF; goto token_ready; }
            *         { kind = TOK_ERROR; goto token_ready; }
        */
    }

token_ready:
    s->cursor = YYCURSOR;
    s->last = (Token){kind, (size_t)(start - s->input),
                            (size_t)(YYCURSOR - s->input)};
    s->finished = kind == TOK_EOF || kind == TOK_ERROR;
    return s->last;
}

static void re2c_close(void *state)
{
    free(state);
}

const Scanner scanner_re2c = {
    .open = re2c_open,
    .next = re2c_next,
    .close = re2c_close
};
