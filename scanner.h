#ifndef SNIRS_SCANNER_H
#define SNIRS_SCANNER_H

#include <stddef.h>

/* Первый этап СНИРС. Общий интерфейс C11. Правила приведены в spec/scanner_spec.txt. */
typedef enum {
    TOK_EOF, TOK_ERROR,
    TOK_IDENT, TOK_NUMBER,
    TOK_IF, TOK_THEN, TOK_ELSE, TOK_END, TOK_WHILE, TOK_DO,
    TOK_FOR, TOK_FROM, TOK_TO, TOK_RETURN, TOK_CASE,
    TOK_ASSIGN, TOK_EQ, TOK_NE, TOK_LT, TOK_LE, TOK_GT, TOK_GE,
    TOK_PLUS, TOK_MINUS, TOK_STAR, TOK_SLASH,
    TOK_LPAREN, TOK_RPAREN, TOK_LBRACKET, TOK_RBRACKET,
    TOK_COMMA, TOK_SEMI, TOK_COLON
} TokenKind;

typedef struct {
    TokenKind kind;
    size_t begin;  /* Первый байт, нумерация с нуля. */
    size_t end;    /* Первый байт за лексемой. */
} Token;

typedef struct {
    /* Отдельный экземпляр для каждого вызова. NULL при сбое подготовки. */
    void *(*open)(const unsigned char *data, size_t length);
    /* Получить очередную лексему. Требуется экземпляр, возвращённый open. */
    Token (*next)(void *state);
    /* Освободить экземпляр с помощью той же реализации, которая его создала. */
    void (*close)(void *state);
} Scanner;

extern const Scanner scanner_table;
extern const Scanner scanner_branch;
extern const Scanner scanner_flex;
extern const Scanner scanner_re2c;

#endif
