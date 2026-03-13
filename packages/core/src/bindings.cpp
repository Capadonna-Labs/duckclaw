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
        .def("get_version", &duckclaw::DuckClaw::get_version, "Obtiene la versión de DuckDB")
        .def("get_schema_context", &duckclaw::DuckClaw::get_schema_context, "Devuelve el esquema DDL y relaciones semánticas de la DB.")
        .def("create_datalake", &duckclaw::DuckClaw::create_datalake, py::arg("folder_path"),
             "Exporta toda la DB a una estructura de Data Lake (Parquet + Schema SQL) lista para la nube.");
}