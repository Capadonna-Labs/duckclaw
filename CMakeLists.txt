cmake_minimum_required(VERSION 3.18)
project(duckclaw)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Pybind11 (required)
find_package(pybind11 REQUIRED)

# DuckDB: prefer system/Homebrew to avoid ~7 min FetchContent build
set(DUCKDB_ROOT "" CACHE PATH "DuckDB install path (e.g. /opt/homebrew/opt/duckdb). Leave empty to build from source.")
if(NOT DUCKDB_ROOT AND APPLE)
    if(EXISTS "/opt/homebrew/opt/duckdb")
        set(DUCKDB_ROOT "/opt/homebrew/opt/duckdb")
    elseif(EXISTS "/usr/local/opt/duckdb")
        set(DUCKDB_ROOT "/usr/local/opt/duckdb")
    endif()
endif()

if(DUCKDB_ROOT)
    find_library(DUCKDB_LIB NAMES duckdb libduckdb PATHS "${DUCKDB_ROOT}/lib" NO_DEFAULT_PATH)
    find_path(DUCKDB_INCLUDE NAMES duckdb.hpp PATHS "${DUCKDB_ROOT}/include" "${DUCKDB_ROOT}/src/include" NO_DEFAULT_PATH)
    if(DUCKDB_LIB AND DUCKDB_INCLUDE)
        add_library(duckdb SHARED IMPORTED)
        set_target_properties(duckdb PROPERTIES
            IMPORTED_LOCATION "${DUCKDB_LIB}"
            INTERFACE_INCLUDE_DIRECTORIES "${DUCKDB_INCLUDE}"
        )
        message(STATUS "Using system DuckDB: ${DUCKDB_ROOT}")
    else()
        set(DUCKDB_ROOT "")
    endif()
endif()

# Fallback: build DuckDB from source (first time can take ~5–7 min)
if(NOT TARGET duckdb_static AND NOT TARGET duckdb)
    message(STATUS "DuckDB not found; building from source (this may take several minutes)...")
    include(FetchContent)
    FetchContent_Declare(
        duckdb
        URL https://github.com/duckdb/duckdb/archive/refs/tags/v1.1.3.tar.gz
    )
    set(BUILD_SHELL OFF CACHE BOOL "" FORCE)
    set(BUILD_UNITTESTS OFF CACHE BOOL "" FORCE)
    set(BUILD_BENCHMARKS OFF CACHE BOOL "" FORCE)
    set(DISABLE_BUILTIN_EXTENSIONS ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(duckdb)
endif()

# Our headers
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)

# Python extension module
pybind11_add_module(_duckclaw src/bindings.cpp src/duckclaw.cpp)
target_include_directories(_duckclaw PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
if(TARGET duckdb_static)
    target_include_directories(_duckclaw PRIVATE ${duckdb_SOURCE_DIR}/src/include)
    target_link_libraries(_duckclaw PRIVATE duckdb_static)
else()
    target_link_libraries(_duckclaw PRIVATE duckdb)
endif()

# Apple Silicon
if(APPLE)
    target_compile_options(_duckclaw PRIVATE "-march=armv8.5-a+sha3+sm4")
endif()