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

enum { SHORT_PASSES = 16 };

static double measure(const Scanner *scanner, const unsigned char *data, size_t length,
                      size_t expected_count, uint64_t expected_checksum, size_t passes)
{
    struct {
        void *state;
        size_t tokens;
        uint64_t checksum;
        Token terminal;
    } scans[SHORT_PASSES];

    for (size_t i = 0; i < passes; ++i) {
        scans[i].state = scanner->open(data, length);
        if (!scans[i].state) fail("timed open failed");
    }

    const uint64_t start = ticks();
    for (size_t i = 0; i < passes; ++i) {
        size_t tokens = 0;
        uint64_t checksum = CHECKSUM_INITIAL;
        Token token;
        for (;;) {
            token = scanner->next(scans[i].state);
            checksum = account(checksum, token);
            if (token.kind == TOK_EOF || token.kind == TOK_ERROR) break;
            ++tokens;
        }
        scans[i].terminal = token;
        scans[i].tokens = tokens;
        scans[i].checksum = checksum;
    }
    const uint64_t stop = ticks();

    for (size_t i = 0; i < passes; ++i) {
        scanner->close(scans[i].state);
        if (!same(scans[i].terminal, (Token){TOK_EOF, length, length}) ||
            scans[i].tokens != expected_count || scans[i].checksum != expected_checksum) {
            fail("timed result mismatch");
        }
    }
    return nanoseconds(stop - start);
}

int benchmark_run(const BenchScanner *variants, size_t count, int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <manifest.tsv> <measurements.csv>\n", argv[0]);
        return EXIT_FAILURE;
    }
#ifdef _WIN32
    LARGE_INTEGER frequency;
    if (!QueryPerformanceFrequency(&frequency)) fail("timer unavailable");
    timer_frequency = (uint64_t)frequency.QuadPart;
#else
    timer_frequency = UINT64_C(1000000000);
#endif
    FILE *manifest = open_file(argv[1], "rb");
    FILE *samples = open_file(argv[2], "wb");
    fputs("input_id,family,input_sha256,variant,round,order,bytes,tokens,passes,elapsed_ns,checksum\n", samples);

    const int rounds = count == 2 ? 16 : 15;
    char line[4096];
    while (fgets(line, sizeof line, manifest)) {
        line[strcspn(line, "\r\n")] = '\0';
        char *name = strtok(line, "\t");
        char *family = strtok(NULL, "\t");
        char *path = strtok(NULL, "\t");
        char *expected_path = strtok(NULL, "\t");
        char *sha256 = strtok(NULL, "\t");
        if (!name || !family || !path || !expected_path || !sha256 || strlen(sha256) != 64 ||
            strtok(NULL, "\t")) fail("bad manifest");

        fprintf(stderr, "%s\n", name);
        size_t length, tokens;
        uint64_t checksum;
        unsigned char *data = load(path, &length);
        if (!length) fail("empty performance workload");
        validate(variants, count, data, length, expected_path, &tokens, &checksum);

        const size_t passes = length < 65536 ? SHORT_PASSES : 1;
        for (size_t v = 0; v < count; ++v) measure(variants[v].scanner, data, length, tokens, checksum, passes);
        for (int round = 0; round < rounds; ++round) {
            for (size_t order = 0; order < count; ++order) {
                const size_t v = ((size_t)round + order) % count;
                const double elapsed = measure(variants[v].scanner, data, length, tokens, checksum, passes);
                if (elapsed <= 0) fail("timer resolution too low");
                if (fprintf(samples, "%s,%s,%s,%s,%d,%" PRIu64 ",%" PRIu64 ",%" PRIu64
                            ",%" PRIu64 ",%.3f,%016" PRIx64 "\n",
                            name, family, sha256, variants[v].name, round + 1, order + 1,
                            (uint64_t)length, (uint64_t)tokens, (uint64_t)passes,
                            elapsed, checksum) < 0) fail("result write failed");
            }
        }
        free(data);
    }
    if (ferror(manifest)) fail("manifest read failed");
    const int input_status = fclose(manifest), output_status = fclose(samples);
    if (input_status || output_status) fail("file close failed");
    return EXIT_SUCCESS;
}
