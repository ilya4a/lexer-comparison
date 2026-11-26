cmake_minimum_required(VERSION 3.16)
project(snirs_scanners LANGUAGES C)

add_executable(test_scanners
    main.c
    "${CMAKE_CURRENT_BINARY_DIR}/generated/scanner_flex.c"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/scanner_re2c.c"
)
target_include_directories(test_scanners PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
set_target_properties(test_scanners PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)
