%option reentrant noyywrap nodefault never-interactive nounput noinput
%option prefix="snirs_flex_"
%option extra-type="FlexState *"

%{
#include "scanner.h"
#include <limits.h>
#include <setjmp.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    yyscan_t engine;
    char *input;
    size_t offset;
    Token last;
    int finished;
    int preparing;
    jmp_buf setup_failure;
} FlexState;

/* yy_scan_buffer вызывает YY_FATAL_ERROR при нехватке памяти.
   При подготовке экземпляра scanner.h требует вернуть NULL. */
static void scanner_failure(yyscan_t engine);
#define YY_FATAL_ERROR(message) scanner_failure(yyscanner)

/* Выполняется перед действием каждого совпавшего правила, включая пропуски. */
#define YY_USER_ACTION                       \
    yyextra->last.begin = yyextra->offset;   \
    yyextra->offset += (size_t)yyleng;       \
    yyextra->last.end = yyextra->offset;
%}

ID      [A-Za-z][A-Za-z0-9]*
NUMBER  [0-9]+
SPACE   [ \t\r\n]+
COMMENT "//"[^\r\n]*

%%
"if"        return TOK_IF;
"then"      return TOK_THEN;
"else"      return TOK_ELSE;
"end"       return TOK_END;
"while"     return TOK_WHILE;
"do"        return TOK_DO;
"for"       return TOK_FOR;
"from"      return TOK_FROM;
"to"        return TOK_TO;
"return"    return TOK_RETURN;
"case"      return TOK_CASE;

{ID}        return TOK_IDENT;
{NUMBER}    return TOK_NUMBER;

":="        return TOK_ASSIGN;
"="         return TOK_EQ;
"!="        return TOK_NE;
"<"         return TOK_LT;
"<="        return TOK_LE;
">"         return TOK_GT;
">="        return TOK_GE;
"+"         return TOK_PLUS;
"-"         return TOK_MINUS;
"*"         return TOK_STAR;
"/"         return TOK_SLASH;
"("         return TOK_LPAREN;
")"         return TOK_RPAREN;
"["         return TOK_LBRACKET;
"]"         return TOK_RBRACKET;
","         return TOK_COMMA;
";"         return TOK_SEMI;
":"         return TOK_COLON;

{SPACE}     { /* Пропустить и искать следующую лексему. */ }
{COMMENT}   { /* Перевод строки обработает SPACE. */ }
.           return TOK_ERROR;
<<EOF>>     return TOK_EOF;
%%

static void scanner_failure(yyscan_t engine)
{
    FlexState *s = yyget_extra(engine);
    if (s->preparing)
        longjmp(s->setup_failure, 1);
    abort(); /* Внутренний сбой flex, а не ошибка во входном тексте. */
}

static void flex_close(void *state)
{
    FlexState *s = state;
    yylex_destroy(s->engine);
    free(s->input);
    free(s);
}

static void *flex_open(const unsigned char *data, size_t length)
{
    /* В C-сканере flex 2.6.x размеры буфера и лексемы хранятся в int. */
    if (length > (size_t)INT_MAX - 2 || (!data && length))
        return NULL;

    FlexState *s = calloc(1, sizeof *s);
    if (!s)
        return NULL;
    s->input = malloc(length + 2);
    if (!s->input || yylex_init_extra(s, &s->engine) != 0) {
        free(s->input);
        free(s);
        return NULL;
    }

    if (length)
        memcpy(s->input, data, length);
    s->input[length] = s->input[length + 1] = 0;

    s->preparing = 1;
    if (setjmp(s->setup_failure)) {
        flex_close(s);
        return NULL;
    }
    /* Создаём стек до буфера: при отказе памяти все выделенные
       ресурсы остаются доступны через s и освобождаются в flex_close. */
    struct yyguts_t *g = (struct yyguts_t *)s->engine;
    g->yy_buffer_stack = calloc(2, sizeof *g->yy_buffer_stack);
    if (!g->yy_buffer_stack) {
        flex_close(s);
        return NULL;
    }
    g->yy_buffer_stack_max = 2;
    yy_scan_buffer(s->input, length + 2, s->engine);
    s->preparing = 0;
    return s;
}

static Token flex_next(void *state)
{
    FlexState *s = state;
    if (!s->finished) {
        s->last.kind = (TokenKind)yylex(s->engine);
        if (s->last.kind == TOK_EOF)
            s->last.begin = s->last.end = s->offset;
        s->finished = s->last.kind == TOK_EOF || s->last.kind == TOK_ERROR;
    }
    return s->last;
}

const Scanner scanner_flex = {
    .open = flex_open,
    .next = flex_next,
    .close = flex_close
};
