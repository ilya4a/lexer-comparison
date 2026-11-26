
#include "scanner_table.h"

#include <new>

#include "dfa_generated.h"

namespace {

using namespace snirs_dfa;

struct Instance {
    const unsigned char *data;
    size_t length;
    size_t position = 0;
    bool stopped = false;
    Token terminal{TOK_EOF, 0, 0};
};

void *scanner_open(const unsigned char *data, size_t length) {
    if (data == nullptr && length != 0) {
        return nullptr;
    }
    return new (std::nothrow) Instance{data, length};
}

void scanner_close(void *state) {
    delete static_cast<Instance *>(state);
}

struct TableTransition {
    static State step(State state, unsigned char symbol_class) {
        return kTransitions[state][symbol_class];
    }
};

struct BranchTransition {
    static State step(State state, unsigned char symbol_class) {
        return branch_delta(state, symbol_class);
    }
};

// Both scanners use this exact algorithm; only delta is a template parameter.
template <class Transition>
Token scanner_next(void *state) {
    auto &input = *static_cast<Instance *>(state);
    if (input.stopped) {
        return input.terminal;
    }

    for (;;) {
        const size_t begin = input.position;
        if (begin == input.length) {
            input.terminal = {TOK_EOF, input.length, input.length};
            input.stopped = true;
            return input.terminal;
        }

        State current = Q_START;
        size_t cursor = begin;
        size_t last_end = begin;
        int last_action = kNoAccept;

        while (cursor < input.length) {
            const auto symbol_class = kByteClass[input.data[cursor]];
            const State next = Transition::step(current, symbol_class);
            if (next == Q_DEAD) {
                break;
            }
            current = next;
            ++cursor;
            const int action = kActions[current];
            if (action != kNoAccept) {
                last_end = cursor;
                last_action = action;
            }
        }

        if (last_action == kNoAccept) {
            input.terminal = {TOK_ERROR, begin, begin + 1};
            input.stopped = true;
            return input.terminal;
        }

        input.position = last_end;
        if (last_action != kSkip) {
            return {static_cast<TokenKind>(last_action), begin, last_end};
        }
        // Skip whitespace/comments without recursion, then restart at q0.
    }
}

} // namespace

extern "C" {
extern const Scanner scanner_table = {
    scanner_open, scanner_next<TableTransition>, scanner_close
};

extern const Scanner scanner_branch = {
    scanner_open, scanner_next<BranchTransition>, scanner_close
};
}
