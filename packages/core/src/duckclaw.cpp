#include "duckclaw.hpp"
#include <cstdio>
#include <fstream>
#include <sstream>
#include <filesystem>

namespace duckclaw {

namespace {

std::string json_escape(const std::string& s) {
    std::ostringstream out;
    for (unsigned char c : s) {
        switch (c) {
            case '"':  out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out << buf;
                } else {
                    out << c;
                }
        }
    }
    return out.str();
}

} // namespace

DuckClaw::DuckClaw(const std::string& db_path) : db(db_path), con(db) {
    if (db_path.empty()) {
        throw std::runtime_error("La ruta de la base de datos no puede estar vacía.");
    }
}

std::string DuckClaw::query(const std::string& sql) {
    auto result = con.Query(sql);
    if (result->HasError()) {
        throw std::runtime_error("DuckDB Query Error: " + result->GetError());
    }

    std::ostringstream json;
    json << "[";
    const auto& names = result->names;
    bool first_row = true;

    for (auto& row : *result) {
        if (!first_row) json << ",";
        first_row = false;
        json << "{";
        for (size_t col_idx = 0; col_idx < names.size(); col_idx++) {
            if (col_idx > 0) json << ",";
            std::string key = json_escape(names[col_idx]);
            std::string val = json_escape(row.GetValue<duckdb::Value>(col_idx).ToString());
            json << "\"" << key << "\":\"" << val << "\"";
        }
        json << "}";
    }
    json << "]";
    return json.str();
}

void DuckClaw::execute(const std::string& sql) {
    auto result = con.Query(sql);
    if (result->HasError()) {
        throw std::runtime_error("DuckDB Execute Error: " + result->GetError());
    }
}

std::string DuckClaw::get_version() const {
    return duckdb::DuckDB::LibraryVersion();
}

std::string DuckClaw::get_schema_context() {
    std::ostringstream oss;

    auto tables_result = con.Query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name"
    );
    if (tables_result->HasError()) {
        throw std::runtime_error("DuckDB Schema Error: " + tables_result->GetError());
    }

    const auto& names = tables_result->names;
    size_t table_name_idx = 0;
    for (size_t i = 0; i < names.size(); i++) {
        if (names[i] == "table_name") {
            table_name_idx = i;
            break;
        }
    }

    for (auto& row : *tables_result) {
        std::string table_name = row.GetValue<duckdb::Value>(table_name_idx).ToString();
        std::string table_esc;
        for (char c : table_name) {
            if (c == '\'') table_esc += "''";
            else table_esc += c;
        }

        oss << "TABLE " << table_name << " (\n";

        auto cols_result = con.Query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name='" + table_esc + "' "
            "ORDER BY ordinal_position"
        );
        if (cols_result->HasError()) {
            oss << "    -- error fetching columns\n";
        } else {
            const auto& col_names = cols_result->names;
            size_t col_name_idx = 0, col_type_idx = 1;
            for (size_t i = 0; i < col_names.size(); i++) {
                if (col_names[i] == "column_name") col_name_idx = i;
                else if (col_names[i] == "data_type") col_type_idx = i;
            }
            bool first = true;
            for (auto& col_row : *cols_result) {
                if (!first) oss << ",\n";
                first = false;
                std::string cname = col_row.GetValue<duckdb::Value>(col_name_idx).ToString();
                std::string ctype = col_row.GetValue<duckdb::Value>(col_type_idx).ToString();
                oss << "    " << cname << " " << ctype;
            }
            oss << "\n";
        }
        oss << ");\n\n";
    }

    try {
        auto rel_result = con.Query("SELECT description FROM schema_relationships");
        if (rel_result && !rel_result->HasError()) {
            oss << "--- RELATIONSHIPS ---\n";
            const auto& rel_names = rel_result->names;
            size_t desc_idx = 0;
            for (size_t i = 0; i < rel_names.size(); i++) {
                if (rel_names[i] == "description") {
                    desc_idx = i;
                    break;
                }
            }
            for (auto& rel_row : *rel_result) {
                std::string desc = rel_row.GetValue<duckdb::Value>(desc_idx).ToString();
                oss << desc << "\n";
            }
        }
    } catch (...) {
        // Tabla schema_relationships no existe; omitir
    }

    return oss.str();
}

void DuckClaw::create_datalake(const std::string& folder_path) {
    if (folder_path.empty()) {
        throw std::runtime_error("create_datalake: la ruta de la carpeta no puede estar vacía.");
    }

    std::filesystem::path base(folder_path);
    std::error_code ec;
    if (!std::filesystem::create_directories(base, ec) && !std::filesystem::exists(base)) {
        throw std::runtime_error("create_datalake: no se pudo crear la carpeta: " + folder_path);
    }

    std::string base_str = base.lexically_normal().string();
    if (base_str.back() != '/' && base_str.back() != '\\') {
        base_str += "/";
    }

    auto tables_result = con.Query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' "
        "AND UPPER(table_type) LIKE '%TABLE%' "
        "ORDER BY table_name"
    );
    if (tables_result->HasError()) {
        throw std::runtime_error("create_datalake: " + tables_result->GetError());
    }

    size_t table_name_idx = 0;
    for (size_t i = 0; i < tables_result->names.size(); i++) {
        if (tables_result->names[i] == "table_name") {
            table_name_idx = i;
            break;
        }
    }

    std::ostringstream schema_sql;
    std::ostringstream load_sql;
    schema_sql << "-- Schema exportado por DuckClaw create_datalake\n\n";
    load_sql << "-- Cargar Parquet en DuckDB: ejecutar schema.sql primero, luego este archivo\n\n";

    size_t exported_tables = 0;
    for (auto& row : *tables_result) {
        std::string table_name = row.GetValue<duckdb::Value>(table_name_idx).ToString();
        std::string table_esc;
        for (char c : table_name) {
            if (c == '\'') table_esc += "''";
            else table_esc += c;
        }

        std::string parquet_path = base_str + table_name + ".parquet";
        std::string parquet_esc;
        for (char c : parquet_path) {
            if (c == '\\') parquet_esc += "\\\\";
            else if (c == '\'') parquet_esc += "''";
            else parquet_esc += c;
        }

        auto copy_result = con.Query(
            "COPY \"" + table_name + "\" TO '" + parquet_esc + "' (FORMAT PARQUET, COMPRESSION 'SNAPPY')"
        );
        if (copy_result->HasError()) {
            throw std::runtime_error("create_datalake (COPY " + table_name + "): " + copy_result->GetError());
        }
        exported_tables++;

        auto cols_result = con.Query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name='" + table_esc + "' "
            "ORDER BY ordinal_position"
        );
        if (cols_result->HasError()) continue;

        schema_sql << "CREATE TABLE IF NOT EXISTS \"" << table_name << "\" (\n";
        const auto& col_names = cols_result->names;
        size_t col_name_idx = 0, col_type_idx = 1;
        for (size_t i = 0; i < col_names.size(); i++) {
            if (col_names[i] == "column_name") col_name_idx = i;
            else if (col_names[i] == "data_type") col_type_idx = i;
        }
        bool first = true;
        for (auto& col_row : *cols_result) {
            if (!first) schema_sql << ",\n";
            first = false;
            std::string cname = col_row.GetValue<duckdb::Value>(col_name_idx).ToString();
            std::string ctype = col_row.GetValue<duckdb::Value>(col_type_idx).ToString();
            schema_sql << "    \"" << cname << "\" " << ctype;
        }
        schema_sql << "\n);\n\n";

        load_sql << "COPY \"" << table_name << "\" FROM '" << parquet_esc << "' (FORMAT PARQUET);\n";
    }

    std::string schema_path = base_str + "schema.sql";
    std::ofstream schema_file(schema_path);
    if (!schema_file) {
        throw std::runtime_error("create_datalake: no se pudo escribir schema.sql en " + base_str);
    }
    schema_file << schema_sql.str();

    std::string load_path = base_str + "load.sql";
    std::ofstream load_file(load_path);
    if (load_file) {
        load_file << load_sql.str();
    }

    if (exported_tables == 0) {
        throw std::runtime_error(
            "create_datalake: no se exportaron tablas. "
            "Verifica que abriste la DB correcta (usa ruta absoluta, p.ej. /.../olist_bi.duckdb)."
        );
    }
}

} // namespace duckclaw