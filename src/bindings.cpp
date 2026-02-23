#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "duckclaw.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_duckclaw, m) {
    m.doc() = "DuckClaw: High-performance analytical memory for IoTCoreLabs agents";

    py::class_<duckclaw::DuckClaw>(m, "DuckClaw")
        .def(py::init<const std::string&>(), py::arg("db_path"))
        .def("query", &duckclaw::DuckClaw::query, "Ejecuta una consulta SQL y devuelve los resultados como JSON (string)")
        .def("execute", &duckclaw::DuckClaw::execute, "Ejecuta una sentencia SQL sin retorno")
        .def("get_version", &duckclaw::DuckClaw::get_version, "Obtiene la versión de DuckDB");
}