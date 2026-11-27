cmake_minimum_required(VERSION 3.16)
project(snirs_scanners LANGUAGES C CXX)

function(add_dfa_library)
    set(BUILD_TESTING OFF)
    add_subdirectory(snirs-dfa EXCLUDE_FROM_ALL)
endfunction()
add_dfa_library()

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
add_executable(experiment_a experiments/a/experiment_a.c)
add_executable(experiment_b experiments/b/experiment_b.c)

foreach(target IN ITEMS scanner_tests experiment_a experiment_b)
    target_link_libraries(${target} PRIVATE scanners)
    set_target_properties(${target} PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)
endforeach()

enable_testing()
add_test(NAME scanner_tests COMMAND scanner_tests
    "${CMAKE_CURRENT_SOURCE_DIR}/pseudocode/pseudocode.txt")
