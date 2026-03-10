-- PowerSealWorker: esquema para productos (cache opcional del catálogo web)
CREATE TABLE IF NOT EXISTS powerseal_worker.products (
  id INTEGER PRIMARY KEY,
  name VARCHAR,
  description VARCHAR,
  category VARCHAR,
  price VARCHAR,
  stock_status VARCHAR,
  url VARCHAR,
  raw_data VARCHAR,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
