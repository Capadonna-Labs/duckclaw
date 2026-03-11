-- FinanzWorker: esquema aislado finance_worker
CREATE TABLE IF NOT EXISTS finance_worker.transactions (
  id INTEGER PRIMARY KEY,
  amount REAL NOT NULL,
  description VARCHAR,
  category_id INTEGER,
  tx_date DATE DEFAULT CURRENT_DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_worker.categories (
  id INTEGER PRIMARY KEY,
  name VARCHAR NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_worker.cuentas (
  id INTEGER PRIMARY KEY,
  name VARCHAR NOT NULL,
  balance REAL DEFAULT 0,
  currency VARCHAR DEFAULT 'COP',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_worker.deudas (
  id INTEGER PRIMARY KEY,
  description VARCHAR,
  amount REAL NOT NULL,
  creditor VARCHAR,
  due_date DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_worker.presupuestos (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_presupuestos_cat_ym ON finance_worker.presupuestos (category_id, year, month);

INSERT INTO finance_worker.categories (id, name) VALUES (1, 'Otros')
ON CONFLICT (id) DO NOTHING;
