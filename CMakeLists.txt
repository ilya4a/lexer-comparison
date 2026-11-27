cmake_minimum_required(VERSION 3.16)
project(snirs_scanners LANGUAGES C CXX)

function(add_dfa_library)
    set(BUILD_TESTING OFF)
    add_subdirectory(snirs-dfa EXCLUDE_FROM_ALL)
endfunction()
add_dfa_library()

option(SNIRS_BUILD_GENERATED_SCANNERS "Build flex/re2c scanners and experiment A" ON)
if(SNIRS_BUILD_GENERATED_SCANNERS)
find_package(FLEX REQUIRED)
find_program(RE2C_EXECUTABLE NAMES re2c)
if(NOT RE2C_EXECUTABLE)
    message(FATAL_ERROR "re2c was not found")
endif()

set(generated_dir "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${generated_dir}")
add_custom_command(
    OUTPUT "${generated_dir}/scanner_flex.c"
    COMMAND "${FLEX_EXECUTABLE}" -8 -Cf -o "${generated_dir}/scanner_flex.c" "${CMAKE_CURRENT_SOURCE_DIR}/flex/scanner.l"
    DEPENDS flex/scanner.l
    VERBATIM
)
add_custom_command(
    OUTPUT "${generated_dir}/scanner_re2c.c"
    COMMAND "${RE2C_EXECUTABLE}" -o "${generated_dir}/scanner_re2c.c" "${CMAKE_CURRENT_SOURCE_DIR}/re2c/scanner.re"
    DEPENDS re2c/scanner.re
    VERBATIM
)

add_library(scanners STATIC
    "${generated_dir}/scanner_flex.c"
    "${generated_dir}/scanner_re2c.c"
)
target_include_directories(scanners PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(scanners PUBLIC snirs_dfa)
set_target_properties(scanners PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)

add_executable(scanner_tests scanner_tests.c)
add_executable(experiment_a experiments/a/experiment_a.c experiments/common/benchmark.c)
target_include_directories(experiment_a PRIVATE experiments/common)
if(MINGW)
    # Enable the C99 printf formats used by both the generated flex code and tests.
    target_compile_definitions(scanners PRIVATE __USE_MINGW_ANSI_STDIO=1)
    target_compile_definitions(scanner_tests PRIVATE __USE_MINGW_ANSI_STDIO=1)
endif()

foreach(target IN ITEMS scanner_tests experiment_a)
    target_link_libraries(${target} PRIVATE scanners)
    set_target_properties(${target} PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS OFF)
endforeach()

enable_testing()
add_test(NAME scanner_tests COMMAND scanner_tests
    "${CMAKE_CURRENT_SOURCE_DIR}/pseudocode/pseudocode.txt")
endif()

# Experiment B uses only the existing DFA library, with no generators needed.
add_executable(experiment_b experiments/b/experiment_b.c experiments/common/benchmark.c)
target_include_directories(experiment_b PRIVATE experiments/common)
target_link_libraries(experiment_b PRIVATE snirs_dfa)
set_target_properties(experiment_b PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS OFF)

add_executable(experiment_b_checks snirs-dfa/tests/scanner_tests.cpp)
target_link_libraries(experiment_b_checks PRIVATE snirs_dfa)
enable_testing()
add_test(NAME experiment_b_contract COMMAND experiment_b_checks)
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(NAME experiment_b_generated_files COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/snirs-dfa/table/generate_dfa.py" --check)
endif()
if(NOT MSVC)
    target_compile_options(experiment_b PRIVATE -Wall -Wextra -Wpedantic)
endif()
