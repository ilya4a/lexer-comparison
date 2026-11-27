#ifndef SNIRS_BENCHMARK_H
#define SNIRS_BENCHMARK_H

#include "scanner.h"
#include <stdint.h>

typedef struct {
    const char *name;
    const Scanner *scanner;
} BenchScanner;

/* TSV manifest: name, family, data path, expected-token path. Paths have no tabs. */
int benchmark_run(const BenchScanner *variants, size_t count, int argc, char **argv);

/* A's five-column manifest appends input_sha256. orders is a row-major schedule. */
int benchmark_run_ordered(const BenchScanner *variants, size_t count, const char *experiment,
                          const size_t *orders, size_t order_rows, int argc, char **argv);

#endif
