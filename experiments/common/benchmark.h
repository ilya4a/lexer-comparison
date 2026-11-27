#ifndef SNIRS_BENCHMARK_H
#define SNIRS_BENCHMARK_H

#include "scanner.h"

typedef struct {
    const char *name;
    const Scanner *scanner;
} BenchScanner;

/* Manifest: input ID, family, data path, expected-token path, SHA-256 (TSV). */
int benchmark_run(const BenchScanner *variants, size_t count, int argc, char **argv);

#endif
