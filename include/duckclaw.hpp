#pragma once
#include <string>
#include <vector>
#include <memory>
#include <map>
#include <duckdb.hpp>

namespace duckclaw {

class DuckClaw {
public:
    explicit DuckClaw(const std::string& db_path);
    ~DuckClaw() = default;

    // Ejecuta una consulta y devuelve los resultados como JSON (string)
    std::string query(const std::string& sql);
    
    // Ejecuta comandos sin retorno (INSERT, UPDATE, CREATE)
    void execute(const std::string& sql);

    // Obtiene la versión de DuckDB para validación
    std::string get_version() const;

private:
    duckdb::DuckDB db;
    duckdb::Connection con;
};

} // namespace duckclaw