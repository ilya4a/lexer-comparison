#!/bin/sh
set -eu

cd "$(dirname "$0")"
case "${1:-tests}" in
    tests)
        target=scanner_tests
        configuration=Debug
        ;;
    a)
        if command -v python3 >/dev/null 2>&1; then
            exec python3 experiments/a/run_experiment.py --build-dir "${2:-build/experiment_a}"
        else
            exec python experiments/a/run_experiment.py --build-dir "${2:-build/experiment_a}"
        fi
        ;;
    b)
        if command -v python3 >/dev/null 2>&1; then
            exec python3 experiments/b/run_experiment.py --build-dir "${2:-build/experiment_b}"
        else
            exec python experiments/b/run_experiment.py --build-dir "${2:-build/experiment_b}"
        fi
        ;;
    *)
        printf 'Usage: %s [tests|a|b] [build-dir]\n' "$0" >&2
        exit 2
        ;;
esac

source_dir=$(pwd -P)
build_base=${2:-build/$target}
build_dir=$build_base
suffix=0

while [ -f "$build_dir/CMakeCache.txt" ]; do
    cached_source=$(sed -n 's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' "$build_dir/CMakeCache.txt")
    cached_build=$(sed -n 's/^CMAKE_CACHEFILE_DIR:INTERNAL=//p' "$build_dir/CMakeCache.txt")
    current_build=$(cd "$build_dir" && pwd -P)
    if [ "$cached_source" = "$source_dir" ] && [ "$cached_build" = "$current_build" ]; then
        break
    fi
    suffix=$((suffix + 1))
    build_dir=$build_base.$suffix
done

if [ "$build_dir" != "$build_base" ]; then
    printf 'CMake cache belongs to another path. Using %s\n' "$build_dir" >&2
fi

cmake -S . -B "$build_dir" -DCMAKE_BUILD_TYPE="$configuration"
cmake --build "$build_dir" --target "$target"

cmake -E chdir "$build_dir" ctest --output-on-failure -R '^scanner_tests$'
