#include "duckclaw.hpp"
#include <cstdio>
#include <sstream>

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

} // namespace duckclaw