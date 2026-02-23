import duckclaw

# Base en memoria para que cada ejecución sea reproducible (sin datos acumulados)
db = duckclaw.DuckClaw(":memory:")

# Crear tabla e insertar
db.execute("CREATE TABLE test (id INTEGER, name TEXT)")
db.execute("INSERT INTO test VALUES (1, 'Slayer-8B'), (2, 'Navigator-3B')")

# Consultar (devuelve JSON por defecto)
result = db.query("SELECT * FROM test")
print(f"Versión de DuckDB: {db.get_version()}")
print(f"Datos en DuckClaw (JSON): {result}")