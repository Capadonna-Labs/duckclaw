-- FinanzWorker: esquema aislado finance_worker
-- Transacciones y categorías
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

-- Cuentas (Bancolombia, Nequi, Efectivo, etc.) — saldo actual por cuenta
CREATE TABLE IF NOT EXISTS finance_worker.cuentas (
  id INTEGER PRIMARY KEY,
  name VARCHAR NOT NULL UNIQUE,
  balance REAL NOT NULL DEFAULT 0,
  currency VARCHAR DEFAULT 'COP',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Presupuestos (límite por período: mensual, etc.)
CREATE TABLE IF NOT EXISTS finance_worker.presupuestos (
  id INTEGER PRIMARY KEY,
  name VARCHAR NOT NULL,
  amount_limit REAL NOT NULL,
  period VARCHAR NOT NULL DEFAULT 'monthly',
  category_id INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO finance_worker.categories (id, name) VALUES (1, 'Otros')
ON CONFLICT (id) DO NOTHING;
