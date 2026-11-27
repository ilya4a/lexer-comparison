#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif

#include "benchmark.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <time.h>
#endif

#define CHECKSUM_INITIAL UINT64_C(14695981039346656037)
#define CHECKSUM_PRIME UINT64_C(1099511628211)

static uint64_t timer_frequency;

static uint64_t ticks(void)
{
#ifdef _WIN32
    LARGE_INTEGER value;
    if (!QueryPerformanceCounter(&value)) abort();
    return (uint64_t)value.QuadPart;
#else
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value)) abort();
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
#endif
}

static double nanoseconds(uint64_t elapsed)
{
    return (double)elapsed * 1e9 / (double)timer_frequency;
}

static uint64_t account(uint64_t checksum, Token token)
{
    checksum = (checksum ^ (uint64_t)token.kind) * CHECKSUM_PRIME;
    checksum = (checksum ^ (uint64_t)token.begin) * CHECKSUM_PRIME;
    return (checksum ^ (uint64_t)token.end) * CHECKSUM_PRIME;
}

static void fail(const char *message)
{
    fprintf(stderr, "ERROR: %s\n", message);
    exit(EXIT_FAILURE);
}

static FILE *open_file(const char *path, const char *mode)
{
    FILE *file = fopen(path, mode);
    if (!file) { perror(path); exit(EXIT_FAILURE); }
    return file;
}

static unsigned char *load(const char *path, size_t *length)
{
    FILE *file = open_file(path, "rb");
    if (fseek(file, 0, SEEK_END)) fail("input seek failed");
    const long size = ftell(file);
    if (size < 0 || (uintmax_t)size > SIZE_MAX) fail("input size failed");
    rewind(file);
    *length = (size_t)size;
    unsigned char *data = malloc(*length ? *length : 1);
    if (!data || fread(data, 1, *length, file) != *length) fail("input read failed");
    if (fclose(file)) fail("input close failed");
    return data;
}

static uint64_t little_endian(const unsigned char *data, size_t size)
{
    uint64_t result = 0;
    for (size_t i = 0; i < size; ++i) result |= (uint64_t)data[i] << (8 * i);
    return result;
}

/* Expected stream is generated independently: <uint32 kind,uint64 begin,uint64 end>. */
static Token expected_token(FILE *file)
{
    unsigned char bytes[20];
    if (fread(bytes, 1, sizeof bytes, file) != sizeof bytes) fail("truncated expectation");
    const uint64_t begin = little_endian(bytes + 4, 8);
    const uint64_t end = little_endian(bytes + 12, 8);
    if (begin > SIZE_MAX || end > SIZE_MAX) fail("expectation exceeds size_t");
    return (Token){(TokenKind)little_endian(bytes, 4), (size_t)begin, (size_t)end};
}

static int same(Token a, Token b)
{
    return a.kind == b.kind && a.begin == b.begin && a.end == b.end;
}

static void validate(const BenchScanner *variants, size_t count, const unsigned char *data,
                     size_t length, const char *expected_path, size_t *tokens, uint64_t *checksum)
{
    void **states = calloc(count, sizeof *states);
    if (!states) fail("state array allocation failed");
    for (size_t v = 0; v < count; ++v) {
        states[v] = variants[v].scanner->open(data, length);
        if (!states[v]) fail("validation open failed");
    }
    FILE *expected = open_file(expected_path, "rb");
    *tokens = 0;
    *checksum = CHECKSUM_INITIAL;
    for (;;) {
        const Token want = expected_token(expected);
        for (size_t v = 0; v < count; ++v) {
            const Token got = variants[v].scanner->next(states[v]);
            if (!same(got, want)) {
                fprintf(stderr, "%s token #%" PRIu64 ": expected %d [%" PRIu64 ",%" PRIu64
                        "), got %d [%" PRIu64 ",%" PRIu64 ")\n",
                        variants[v].name, (uint64_t)*tokens, (int)want.kind,
                        (uint64_t)want.begin, (uint64_t)want.end,
                        (int)got.kind, (uint64_t)got.begin, (uint64_t)got.end);
                fail("token sequence mismatch");
            }
        }
        *checksum = account(*checksum, want);
        if (want.kind == TOK_ERROR) fail("lexical error in workload");
        if (want.kind == TOK_EOF) {
            if (want.begin != length || want.end != length) fail("early EOF");
            if (fgetc(expected) != EOF || ferror(expected)) fail("extra expected tokens/read error");
            for (size_t v = 0; v < count; ++v) {
                if (!same(variants[v].scanner->next(states[v]), want)) fail("unstable EOF");
            }
            break;
        }
        ++*tokens;
    }
    if (fclose(expected)) fail("expectation close failed");
    for (size_t v = 0; v < count; ++v) variants[v].scanner->close(states[v]);
    free(states);
}

static double measure(const Scanner *scanner, const unsigned char *data, size_t length,
                      size_t expected_count, uint64_t expected_checksum)
{
    void *state = scanner->open(data, length);
    if (!state) fail("timed open failed");
    size_t tokens = 0;
    uint64_t checksum = CHECKSUM_INITIAL;
    Token token;
    const uint64_t start = ticks();
    for (;;) {
        token = scanner->next(state);
        checksum = account(checksum, token);
        if (token.kind == TOK_EOF || token.kind == TOK_ERROR) break;
        ++tokens;
    }
    const uint64_t stop = ticks();
    scanner->close(state);
    if (token.kind != TOK_EOF || token.begin != length || token.end != length ||
        tokens != expected_count || checksum != expected_checksum) fail("timed result mismatch");
    return nanoseconds(stop - start);
}

static int run_internal(const BenchScanner *variants, size_t count, const char *experiment,
                        const size_t *orders, size_t order_rows, int argc, char **argv)
{
    int validation_only = argc == 5 && strcmp(argv[1], "--validate-only") == 0;
    if (validation_only) { --argc; ++argv; }
    if (argc != 4 || count == 0 || order_rows == 0) {
        fprintf(stderr, "Usage: %s [--validate-only] <manifest.tsv> <measurements.csv> <validation.csv>\n", argv[0]);
        return EXIT_FAILURE;
    }
    for (size_t row = 0; row < order_rows; ++row) {
        for (size_t position = 0; position < count; ++position) {
            const size_t value = orders[row * count + position];
            if (value >= count) fail("invalid schedule index");
            for (size_t previous = 0; previous < position; ++previous) {
                if (orders[row * count + previous] == value) fail("duplicate schedule index");
            }
        }
    }
#ifdef _WIN32
    LARGE_INTEGER frequency;
    if (!QueryPerformanceFrequency(&frequency)) fail("timer unavailable");
    timer_frequency = (uint64_t)frequency.QuadPart;
#else
    timer_frequency = UINT64_C(1000000000);
#endif
    uint64_t minimum = UINT64_MAX, total = 0;
    for (int i = 0; i < 10000; ++i) {
        const uint64_t start = ticks();
        const uint64_t stop = ticks();
        const uint64_t elapsed = stop - start;
        if (elapsed < minimum) minimum = elapsed;
        total += elapsed;
    }
    printf("Timer frequency=%" PRIu64 " Hz; empty interval min=%.1f ns, mean=%.1f ns (10000 pairs)\n",
           timer_frequency, nanoseconds(minimum), nanoseconds(total) / 10000.0);

    FILE *manifest = open_file(argv[1], "rb");
    FILE *samples = open_file(argv[2], "wb");
    FILE *validation = open_file(argv[3], "wb");
    if (experiment) {
        fputs("experiment,input_id,input_sha256,variant,round,order,bytes,tokens,elapsed_ns,checksum\n", samples);
    } else {
        fputs("input,family,bytes,tokens,round,order,variant,elapsed_ns,ns_per_byte,tokens_per_second,checksum\n", samples);
    }
    fputs("input,bytes,tokens,checksum,full_token_match,eof_match\n", validation);
    char line[4096];
    while (fgets(line, sizeof line, manifest)) {
        line[strcspn(line, "\r\n")] = '\0';
        char *name = strtok(line, "\t");
        char *family = strtok(NULL, "\t");
        char *path = strtok(NULL, "\t");
        char *expected_path = strtok(NULL, "\t");
        char *sha256 = experiment ? strtok(NULL, "\t") : NULL;
        if (!name || !family || !path || !expected_path || (experiment && (!sha256 || strlen(sha256) != 64)) ||
            strtok(NULL, "\t")) fail("bad manifest");
        printf("Validating input %s\n", name);
        fflush(stdout);
        size_t length, tokens;
        uint64_t checksum;
        unsigned char *data = load(path, &length);
        if (!length) fail("empty performance workload");
        validate(variants, count, data, length, expected_path, &tokens, &checksum);
        fprintf(validation, "%s,%" PRIu64 ",%" PRIu64 ",%016" PRIx64 ",true,true\n",
                name, (uint64_t)length, (uint64_t)tokens, checksum);
        fflush(validation);
        if (validation_only) {
            printf("Validated %s through EOF\n", name);
            free(data);
            continue;
        }
        // Exactly one warm-up per implementation/input, excluded from statistics.
        for (size_t v = 0; v < count; ++v) measure(variants[v].scanner, data, length, tokens, checksum);
        for (int round = 1; round <= 16; ++round) {
            for (size_t order = 0; order < count; ++order) {
                const size_t v = orders[((size_t)(round - 1) % order_rows) * count + order];
                const double elapsed = measure(variants[v].scanner, data, length, tokens, checksum);
                if (experiment) {
                    fprintf(samples, "%s,%s,%s,%s,%d,%" PRIu64 ",%" PRIu64 ",%" PRIu64
                            ",%.0f,%016" PRIx64 "\n", experiment, name, sha256, variants[v].name,
                            round, (uint64_t)(order + 1), (uint64_t)length, (uint64_t)tokens, elapsed, checksum);
                } else {
                    fprintf(samples, "%s,%s,%" PRIu64 ",%" PRIu64 ",%d,%" PRIu64
                        ",%s,%.3f,%.9f,%.3f,%016" PRIx64 "\n",
                        name, family, (uint64_t)length, (uint64_t)tokens, round,
                        (uint64_t)(order + 1), variants[v].name,
                        elapsed, elapsed / (double)length, (double)tokens * 1e9 / elapsed, checksum);
                }
            }
        }
        fflush(samples);
        printf("Validated EOF + measured 16 rounds x %" PRIu64 " variants: %s (%" PRIu64 " bytes, %" PRIu64
               " tokens, %016" PRIx64 ")\n", (uint64_t)count, name, (uint64_t)length, (uint64_t)tokens, checksum);
        fflush(stdout);
        free(data);
    }
    if (ferror(manifest)) fail("manifest read failed");
    const int a = fclose(manifest), b = fclose(samples), c = fclose(validation);
    if (a || b || c) fail("result close failed");
    return EXIT_SUCCESS;
}

int benchmark_run(const BenchScanner *variants, size_t count, int argc, char **argv)
{
    const size_t pairs[] = {0, 1, 1, 0};
    if (count != 2) fail("legacy B entry requires two variants");
    return run_internal(variants, count, NULL, pairs, 2, argc, argv);
}

int benchmark_run_ordered(const BenchScanner *variants, size_t count, const char *experiment,
                          const size_t *orders, size_t order_rows, int argc, char **argv)
{
    return run_internal(variants, count, experiment, orders, order_rows, argc, argv);
}
