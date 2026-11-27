#include "table/scanner_table.h"
#include <stdio.h>

static void run_scanner(const Scanner *scanner)
{
    (void)scanner;
    /* TODO: measure a full pass on the same inputs for both DFA variants. */
}

int main(void)
{
    run_scanner(&scanner_table);
    run_scanner(&scanner_branch);
    puts("Experiment B: scaffold");
    return 0;
}
