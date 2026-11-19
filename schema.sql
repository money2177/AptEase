CREATE TABLE IF NOT EXISTS units (
 id INTEGER PRIMARY KEY, block TEXT NOT NULL, number TEXT NOT NULL,
 bedrooms INTEGER NOT NULL CHECK(bedrooms BETWEEN 1 AND 8), UNIQUE(block,number)
);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','resident','guard'))
);
CREATE TABLE IF NOT EXISTS occupancies (
 id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES units(id),
 user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL CHECK(kind IN ('Owner','Tenant')),
 start_date TEXT NOT NULL, end_date TEXT CHECK(end_date >= start_date)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_home ON occupancies(user_id) WHERE end_date IS NULL;
CREATE INDEX IF NOT EXISTS occupancy_unit ON occupancies(unit_id,end_date);
CREATE TABLE IF NOT EXISTS bills (
 id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES units(id),
 period TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0), due_date TEXT NOT NULL,
 UNIQUE(unit_id,period)
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES bills(id),
 amount INTEGER NOT NULL CHECK(amount > 0), reference TEXT NOT NULL UNIQUE,
 paid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS payments_bill ON payments(bill_id);
CREATE TRIGGER IF NOT EXISTS prevent_overpayment BEFORE INSERT ON payments
BEGIN
 SELECT CASE WHEN NEW.amount + COALESCE((SELECT SUM(amount) FROM payments WHERE bill_id=NEW.bill_id),0)
 > (SELECT amount FROM bills WHERE id=NEW.bill_id) THEN RAISE(ABORT,'Payment exceeds outstanding balance') END;
END;
CREATE VIEW IF NOT EXISTS bill_balances AS
 SELECT b.*, COALESCE(SUM(p.amount),0) AS paid, b.amount-COALESCE(SUM(p.amount),0) AS balance
 FROM bills b LEFT JOIN payments p ON p.bill_id=b.id GROUP BY b.id;
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY, occupancy_id INTEGER NOT NULL REFERENCES occupancies(id),
 subject TEXT NOT NULL, description TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','In progress','Resolved')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS visits (
 id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES units(id),
 visitor TEXT NOT NULL, purpose TEXT NOT NULL, arrived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 departed_at TEXT
);
CREATE TABLE IF NOT EXISTS complaints (
 id INTEGER PRIMARY KEY, occupancy_id INTEGER NOT NULL REFERENCES occupancies(id),
 category TEXT NOT NULL CHECK(category IN ('Noise','Cleanliness','Security','Shared spaces','Other')),
 subject TEXT NOT NULL, description TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','In progress','Resolved')),
 response TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS complaints_occupancy ON complaints(occupancy_id);
CREATE TABLE IF NOT EXISTS notices (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS parking (
 id INTEGER PRIMARY KEY, slot TEXT NOT NULL UNIQUE,
 unit_id INTEGER REFERENCES units(id), vehicle TEXT UNIQUE,
 CHECK((unit_id IS NULL) = (vehicle IS NULL))
);
CREATE TABLE IF NOT EXISTS facilities (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS bookings (
 id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL REFERENCES facilities(id),
 occupancy_id INTEGER NOT NULL REFERENCES occupancies(id),
 day TEXT NOT NULL, hour INTEGER NOT NULL CHECK(hour BETWEEN 8 AND 20),
 UNIQUE(facility_id,day,hour)
);
