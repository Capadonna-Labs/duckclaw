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

    // Devuelve el esquema DDL y relaciones semánticas de la DB (para contexto de LLM)
    std::string get_schema_context();

    // Exporta toda la DB a una estructura de Data Lake (Parquet + schema.sql) lista para Fabric/S3
    void create_datalake(const std::string& folder_path);

private:
    duckdb::DuckDB db;
    duckdb::Connection con;
};

} // namespace duckclaw