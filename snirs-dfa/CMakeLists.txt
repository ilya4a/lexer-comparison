cmake_minimum_required(VERSION 3.16)
project(snirs_dfa LANGUAGES C CXX)

add_library(snirs_dfa STATIC table/scanner_table.cpp)
target_compile_features(snirs_dfa PUBLIC cxx_std_17)
target_include_directories(snirs_dfa PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/..") # Shared scanner.h belongs to the comparison project.
set_target_properties(snirs_dfa PROPERTIES CXX_EXTENSIONS OFF)
if(MSVC)
    target_compile_options(snirs_dfa PRIVATE /W4 /utf-8)
else()
    target_compile_options(snirs_dfa PRIVATE -Wall -Wextra -Wpedantic)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(scanner_tests tests/scanner_tests.cpp)
    target_link_libraries(scanner_tests PRIVATE snirs_dfa)
    add_test(NAME scanner_contract COMMAND scanner_tests)

    add_executable(scanner_c_interface tests/c_interface_test.c)
    set_target_properties(scanner_c_interface PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)
    target_link_libraries(scanner_c_interface PRIVATE snirs_dfa)
    add_test(NAME scanner_c_interface COMMAND scanner_c_interface)

    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_test(NAME scanner_generated_files
            COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/table/generate_dfa.py" --check)
    endif()
endif()
