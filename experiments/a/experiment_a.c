#include "benchmark.h"

int main(int argc, char **argv)
{
    const BenchScanner variants[] = {
        {"flex", &scanner_flex}, {"re2c", &scanner_re2c},
        {"table", &scanner_table}, {"branch", &scanner_branch}
    };
    const size_t orders[][4] = {
        {0, 1, 3, 2}, {1, 2, 0, 3}, {2, 3, 1, 0}, {3, 0, 2, 1}
    };
    return benchmark_run_ordered(variants, 4, "A", &orders[0][0], 4, argc, argv);
}
