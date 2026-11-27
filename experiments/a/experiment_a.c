#include "benchmark.h"

int main(int argc, char **argv)
{
    const BenchScanner variants[] = {
        {"flex", &scanner_flex}, {"re2c", &scanner_re2c}, {"table", &scanner_table}
    };
    return benchmark_run(variants, sizeof variants / sizeof variants[0], argc, argv);
}
