#include "scanner.h"
#include <stdio.h>

static void run_scanner(const Scanner *scanner)
{
    (void)scanner;
    /* TODO: measure a full pass on each prepared input. */
}

int main(void)
{
    run_scanner(&scanner_flex);
    run_scanner(&scanner_re2c);
    run_scanner(&scanner_table);
    puts("Experiment A: scaffold");
    return 0;
}
