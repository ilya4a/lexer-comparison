#include "table/scanner_table.h"
#include "table/dfa_generated.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#elif defined(__unix__) || defined(__APPLE__)
#include <sys/mman.h>
#include <unistd.h>
#endif

namespace {

using Bytes = std::vector<unsigned char>;
const std::array<const Scanner *, 2> scanners{{&scanner_table, &scanner_branch}};
size_t checked_inputs = 0;

void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

bool equal(Token a, Token b) {
    return a.kind == b.kind && a.begin == b.begin && a.end == b.end;
}

bool letter(unsigned char c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

bool digit(unsigned char c) {
    return c >= '0' && c <= '9';
}

// Independent procedural oracle: no DFA, generated classes, or transition code.
std::vector<Token> reference(const Bytes &data) {
    static constexpr std::pair<std::string_view, TokenKind> keywords[] = {
        {"if", TOK_IF}, {"then", TOK_THEN}, {"else", TOK_ELSE}, {"end", TOK_END},
        {"while", TOK_WHILE}, {"do", TOK_DO}, {"for", TOK_FOR}, {"from", TOK_FROM},
        {"to", TOK_TO}, {"return", TOK_RETURN}, {"case", TOK_CASE}
    };
    static constexpr std::pair<std::string_view, TokenKind> signs[] = {
        {":=", TOK_ASSIGN}, {"!=", TOK_NE}, {"<=", TOK_LE}, {">=", TOK_GE},
        {"=", TOK_EQ}, {"<", TOK_LT}, {">", TOK_GT}, {"+", TOK_PLUS},
        {"-", TOK_MINUS}, {"*", TOK_STAR}, {"/", TOK_SLASH}, {"(", TOK_LPAREN},
        {")", TOK_RPAREN}, {"[", TOK_LBRACKET}, {"]", TOK_RBRACKET},
        {",", TOK_COMMA}, {";", TOK_SEMI}, {":", TOK_COLON}
    };
    std::vector<Token> result;
    size_t pos = 0;
    while (pos < data.size()) {
        const auto c = data[pos];
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') {
            ++pos;
            continue;
        }
        if (c == '/' && pos + 1 < data.size() && data[pos + 1] == '/') {
            pos += 2;
            while (pos < data.size() && data[pos] != '\r' && data[pos] != '\n') ++pos;
            continue;
        }
        const size_t begin = pos;
        if (letter(c)) {
            do { ++pos; } while (pos < data.size() && (letter(data[pos]) || digit(data[pos])));
            TokenKind kind = TOK_IDENT;
            const std::string_view spelling(reinterpret_cast<const char *>(data.data() + begin), pos - begin);
            for (const auto &keyword : keywords) {
                if (spelling == keyword.first) kind = keyword.second;
            }
            result.push_back({kind, begin, pos});
        } else if (digit(c)) {
            do { ++pos; } while (pos < data.size() && digit(data[pos]));
            result.push_back({TOK_NUMBER, begin, pos});
        } else {
            bool found = false;
            for (const auto &sign : signs) {
                if (sign.first.size() <= data.size() - pos &&
                    std::equal(sign.first.begin(), sign.first.end(), data.begin() + pos)) {
                    pos += sign.first.size();
                    result.push_back({sign.second, begin, pos});
                    found = true;
                    break;
                }
            }
            if (!found) {
                result.push_back({TOK_ERROR, begin, begin + 1});
                return result;
            }
        }
    }
    result.push_back({TOK_EOF, data.size(), data.size()});
    return result;
}

void verify(const Scanner &scanner, const unsigned char *data, size_t length,
            const std::vector<Token> &expected) {
    std::unique_ptr<void, void (*)(void *)> state(scanner.open(data, length), scanner.close);
    require(state != nullptr, "open failed");
    for (Token token : expected) {
        const Token actual = scanner.next(state.get());
        if (!equal(actual, token)) {
            std::cerr << "input #" << checked_inputs << ", length " << length
                      << ": expected " << token.kind << " [" << token.begin << ',' << token.end
                      << "), got " << actual.kind << " [" << actual.begin << ',' << actual.end << ")\n";
            throw std::runtime_error("token mismatch");
        }
    }
    require(!expected.empty(), "empty expectation");
    for (int i = 0; i < 3; ++i) {
        require(equal(scanner.next(state.get()), expected.back()), "terminal token is not stable");
    }
}

void check(const Bytes &data) {
    const auto expected = reference(data);
    const auto original = data;
    ++checked_inputs;
    for (const Scanner *scanner : scanners) {
        verify(*scanner, data.data(), data.size(), expected);
        require(data == original, "scanner changed input");
    }
}

void example(std::string_view text, std::initializer_list<Token> expected) {
    const Bytes data(text.begin(), text.end());
    ++checked_inputs;
    for (const Scanner *scanner : scanners) {
        verify(*scanner, data.data(), data.size(), expected);
    }
}

void examples() {
    example("", {{TOK_EOF, 0, 0}});
    example("if", {{TOK_IF, 0, 2}, {TOK_EOF, 2, 2}});
    example("if2", {{TOK_IDENT, 0, 3}, {TOK_EOF, 3, 3}});
    example("if:=15", {{TOK_IF, 0, 2}, {TOK_ASSIGN, 2, 4}, {TOK_NUMBER, 4, 6}, {TOK_EOF, 6, 6}});
    example("abc", {{TOK_IDENT, 0, 3}, {TOK_EOF, 3, 3}});
    example("//no newline", {{TOK_EOF, 12, 12}});
    example("if_", {{TOK_IF, 0, 2}, {TOK_ERROR, 2, 3}});
    example("!", {{TOK_ERROR, 0, 1}});
    example("!x", {{TOK_ERROR, 0, 1}});
    example(" / //x\r\n:!=<=", {{TOK_SLASH, 1, 2}, {TOK_COLON, 8, 9},
            {TOK_NE, 9, 11}, {TOK_LE, 11, 13}, {TOK_EOF, 13, 13}});
    example("-001 12abc", {{TOK_MINUS, 0, 1}, {TOK_NUMBER, 1, 4},
            {TOK_NUMBER, 5, 7}, {TOK_IDENT, 7, 10}, {TOK_EOF, 10, 10}});
    example(std::string_view("//\0\xFF\nif", 7), {{TOK_IF, 5, 7}, {TOK_EOF, 7, 7}});
    example(std::string_view("if\0x", 4), {{TOK_IF, 0, 2}, {TOK_ERROR, 2, 3}});

    const std::string words[] = {"if", "then", "else", "end", "while", "do",
                                 "for", "from", "to", "return", "case"};
    for (const auto &word : words) {
        for (size_t length = 1; length <= word.size(); ++length) {
            check(Bytes(word.begin(), word.begin() + length));
        }
        for (const std::string suffix : {"2", "X", "if", "_", ":="}) {
            const auto text = word + suffix;
            check(Bytes(text.begin(), text.end()));
        }
        auto upper = word;
        upper[0] = static_cast<char>(upper[0] - 'a' + 'A');
        check(Bytes(upper.begin(), upper.end()));
    }
    const std::string all = "if then else end while do for from to return case "
                            ":= = != < <= > >= + - * / ( ) [ ] , ; :";
    check(Bytes(all.begin(), all.end()));
}

void lifetimes() {
    for (const Scanner *scanner : scanners) {
        verify(*scanner, nullptr, 0, {{TOK_EOF, 0, 0}});
        require(scanner->open(nullptr, 1) == nullptr, "invalid input accepted");
        const unsigned char first[] = {'i', 'f', '2'};
        const unsigned char second[] = {'1', ' ', '2'};
        std::unique_ptr<void, void (*)(void *)> a(scanner->open(first, 3), scanner->close);
        std::unique_ptr<void, void (*)(void *)> b(scanner->open(second, 3), scanner->close);
        require(a != nullptr && b != nullptr, "open failed");
        require(equal(scanner->next(a.get()), {TOK_IDENT, 0, 3}), "independent input a failed");
        require(equal(scanner->next(b.get()), {TOK_NUMBER, 0, 1}), "independent input b failed");
        require(equal(scanner->next(a.get()), {TOK_EOF, 3, 3}), "independent EOF failed");
        require(equal(scanner->next(b.get()), {TOK_NUMBER, 2, 3}), "independent cursor failed");
        // b is deliberately closed before requesting EOF.
        void *early = scanner->open(first, 3);
        require(early != nullptr, "early close open failed");
        scanner->close(early); // close before the first next
    }
}

void differential_inputs() {
    check({});
    // Every byte and every pair, including embedded NUL and high bytes.
    for (unsigned int a = 0; a < 256; ++a) {
        check({static_cast<unsigned char>(a)});
        for (unsigned int b = 0; b < 256; ++b) {
            check({static_cast<unsigned char>(a), static_cast<unsigned char>(b)});
        }
        Bytes comment{'/', '/', static_cast<unsigned char>(a)};
        check(comment);
        comment.insert(comment.end(), {'\r', '\n', 'i', 'f'});
        check(comment);
        // Error positions after a complete valid token and a skip.
        check({'i', 'f', ' ', static_cast<unsigned char>(a), 'x'});
    }

    std::mt19937 rng(0x534E4952u);
    const std::string atoms[] = {"if", "then", "else", "while", "return", "case",
        "ifx", "while2", "abc123", "00007", ":=", "!=", "<=", ">=", "+", "-",
        "*", "/", "(", ")", "[", "]", ",", ";", ":", " ", "\t\r\n", "//comment\n"};
    for (int trial = 0; trial < 5000; ++trial) {
        Bytes random(rng() % 128);
        for (auto &byte : random) byte = static_cast<unsigned char>(rng() & 255u);
        check(random);

        Bytes mixed;
        const auto count = 1 + rng() % 80;
        for (unsigned int i = 0; i < count; ++i) {
            const auto &atom = atoms[rng() % std::size(atoms)];
            mixed.insert(mixed.end(), atom.begin(), atom.end());
        }
        check(mixed);
        mixed.insert(mixed.begin() + (rng() % (mixed.size() + 1)),
                     static_cast<unsigned char>(rng() & 255u));
        check(mixed);
    }
    check(Bytes(100000, 'a'));
    check(Bytes(100000, '0'));
    check(Bytes(100000, ' '));
    Bytes long_comment{'/', '/'};
    for (int i = 0; i < 100000; ++i) {
        auto byte = static_cast<unsigned char>(rng() & 255u);
        if (byte == '\r' || byte == '\n') byte = 0;
        long_comment.push_back(byte);
    }
    check(long_comment);
    Bytes many_comments;
    for (int i = 0; i < 20000; ++i) many_comments.insert(many_comments.end(), {'/', '/', '\n'});
    check(many_comments);
}

void transition_equivalence() {
    using namespace snirs_dfa;
    for (size_t q = 0; q < kStateCount; ++q) {
        for (unsigned int byte = 0; byte < 256; ++byte) {
            const auto state = static_cast<State>(q);
            const auto c = kByteClass[byte];
            require(kTransitions[state][c] == branch_delta(state, c), "delta representations differ");
        }
    }
}

// Put the input immediately before an inaccessible page, with no sentinel.
// Making the input page read-only also detects accidental writes.
void guarded_input() {
#if defined(_WIN32) || defined(__unix__) || defined(__APPLE__)
#ifdef _WIN32
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    const size_t page_size = info.dwPageSize;
    auto *memory = static_cast<unsigned char *>(VirtualAlloc(nullptr, 2 * page_size,
        MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    require(memory != nullptr, "VirtualAlloc failed");
    struct Release { unsigned char *p; ~Release() { VirtualFree(p, 0, MEM_RELEASE); } } release{memory};
    DWORD old;
    require(VirtualProtect(memory + page_size, page_size, PAGE_NOACCESS, &old) != 0, "guard failed");
#else
    const size_t page_size = static_cast<size_t>(sysconf(_SC_PAGESIZE));
    auto *memory = static_cast<unsigned char *>(mmap(nullptr, 2 * page_size,
        PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    require(memory != MAP_FAILED, "mmap failed");
    struct Release { unsigned char *p; size_t n; ~Release() { munmap(p, n); } } release{memory, 2 * page_size};
    require(mprotect(memory + page_size, page_size, PROT_NONE) == 0, "guard failed");
#endif
    const std::vector<Bytes> inputs = {{}, {'i', 'f'}, {'i', 'f', '2'}, {'1'}, {':'}, {'!'},
        {'/'}, {'/', '/'}, {'/', '/', 0, 0xFF}, {0}, {0xFF}, {' '}, {'\r', '\n'}, {'<', '='}};
    for (const auto &input : inputs) {
#ifdef _WIN32
        require(VirtualProtect(memory, page_size, PAGE_READWRITE, &old) != 0, "unprotect failed");
#else
        require(mprotect(memory, page_size, PROT_READ | PROT_WRITE) == 0, "unprotect failed");
#endif
        auto *data = memory + page_size - input.size();
        std::copy(input.begin(), input.end(), data);
#ifdef _WIN32
        require(VirtualProtect(memory, page_size, PAGE_READONLY, &old) != 0, "protect failed");
#else
        require(mprotect(memory, page_size, PROT_READ) == 0, "protect failed");
#endif
        for (const Scanner *scanner : scanners) verify(*scanner, data, input.size(), reference(input));
    }
#endif
}

} // namespace

int main() {
    try {
        transition_equivalence();
        examples();
        lifetimes();
        differential_inputs();
        guarded_input();
        std::cout << "Passed: " << checked_inputs << " inputs against independent reference; "
                  << "all transitions, terminal tokens, C-compatible interface, "
                  << "independent instances, and guarded buffers.\n";
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
