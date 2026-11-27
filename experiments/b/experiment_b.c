#include "benchmark.h"

int main(int argc, char **argv)
{
    const BenchScanner variants[] = {
        {"table", &scanner_table},
        {"branch", &scanner_branch}
    };
    return benchmark_run(variants, sizeof variants / sizeof variants[0], argc, argv);
}
