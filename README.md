# AptEase Apartment Management System

DBMS mini-project by **Aditi M Hubli (PES1UG24CS652)** and **Fathima Zahra (PES1UG24CS664)**.

AptEase manages a fictional apartment community. The local web app uses Python, server-rendered HTML, CSS and three storage types. The setup below was tested with Python 3.13 on Windows. Confirm any required database products against your course rubric before submission.
 
| Database type | Technology | What it stores |
|---|---|---|
| Relational SQL | MySQL 8.0.16+ | Accounts, units, occupancies, bills, payments, complaints, bookings and other operational records |
| Document NoSQL | TinyDB | Community directory entries with nested contact details and optional hours |
| Vector database | sqlite-vec in a separate SQLite file | Help articles and their numeric topic vectors. The vector engine retrieves nearest neighbors by cosine distance. |

The web app connects to a MySQL server. The document store and help search run locally. Help search uses a small hand-built vocabulary and six topic dimensions. For example, searching for `neighbors are too loud` finds the complaints article.

## Implemented features

| Module | Workflow |
|---|---|
| Role-based access | Administrators and gate staff use provisioned accounts. Residents create individual accounts and sign in after management approval. |
| Apartments and residents | Add apartments, approve Owner or Tenant registration requests, record move-ins and move-outs, and review occupancy history. |
| Maintenance dues | Issue one bill per apartment per month, record full or partial payments, and see the outstanding balance, overdue status and payment ledger. |
| Service requests | Residents submit and track their requests. Administrators update their status. |
| Complaints | Residents file categorized complaints and track their status and management response. Administrators review and respond from a dedicated register. |
| Visitor access | Guests request a visit for a specific apartment. Residents approve or decline requests for their apartment, and gate staff check in approved guests. Gate staff can also log walk-ins and departures. |
| Parking | Administrators create, allocate and release spaces. Residents see assignments for their apartment. |
| Facilities | Register facilities, view reserved slots, book one-hour slots and cancel future reservations. A database constraint prevents duplicate slots. |
| Notice board | Administrators publish notices for all roles. |
| Community directory | Signed-in users browse contacts. Administrators add or remove entries stored in TinyDB. |
| Help search | Signed-in users retrieve relevant help articles by vector similarity. |
| Dashboard and reports | View occupancy, outstanding dues, open tickets and on-site visitor counts by role. Example SQL reports are in the presentation guide. |

The app is a local academic demo with sample accounts, one community, manual payment recording and in-memory login sessions. Use fictional resident, vehicle and visitor details. Billing, parking and visitor records follow the apartment. Request and booking histories follow the resident who created them.

## Run on Windows

In MySQL Workbench, connect as a MySQL administrator and run the commands below
once. Replace the sample password with your own password.

```sql
CREATE DATABASE aptease CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'aptease'@'localhost' IDENTIFIED BY 'replace-with-your-password';
GRANT ALL PRIVILEGES ON aptease.* TO 'aptease'@'localhost';
```

If the Windows `MySQL80` service is stopped, start it from Services or run
`Start-Service MySQL80` in an administrator PowerShell window.

Open PowerShell in the project folder. The default MySQL address is
`127.0.0.1:3306`. Set `APTEASE_MYSQL_HOST`, `APTEASE_MYSQL_PORT`, and
`APTEASE_MYSQL_USER` if your setup differs.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$mysqlPassword = Read-Host 'MySQL password' -AsSecureString
$env:APTEASE_MYSQL_PASSWORD = [System.Net.NetworkCredential]::new('', $mysqlPassword).Password
.\.venv\Scripts\python.exe app.py
```

Open [AptEase](http://127.0.0.1:8000). First launch creates the tables,
billing view and payment triggers inside MySQL. TinyDB and help search use
`aptease.sqlite3.directory.json` and `aptease.sqlite3.vectors.sqlite3`.
Stop with Ctrl+C. Use `--mysql-database NAME` with another existing MySQL
database to keep rehearsal data separate, and `--db rehearsal.sqlite3` to
select separate companion files.

### Import existing AptEase data

Stop the old app first and run this before starting the app against the MySQL
database for the first time. A normal first launch seeds staff accounts, so
use a fresh database if you already started the app.

```powershell
.\.venv\Scripts\python.exe app.py --import-sqlite aptease.sqlite3
```

This copies the relational records, including user accounts and password hashes,
into MySQL. Use the actual old filename if you used `cedar.sqlite3` or
`rehearsal.sqlite3`. On subsequent runs omit `--import-sqlite`. For a
custom source filename, keep using `--db SOURCE_FILENAME` to select its
existing document and vector files. If your MySQL database also has a custom
name, pass the same `--mysql-database NAME` on each run.

| Staff role | Username | Initial local password |
|---|---|---|
| Administrator | `admin` | `AdminDemo123` |
| Gate staff | `guard` | `GuardDemo123` |

On a fresh database, sign in as admin and add the apartments under **Units & residents**. An empty MySQL database starts with the two staff accounts and empty operational records. Imported databases keep their existing accounts.

1. From the sign-in screen, select **Create a resident account**.
2. Choose **Owner** or **Tenant** and your apartment, then choose a username and a password of at least eight characters.
3. Management verifies the occupant and opens **Units & residents → Resident approvals**. Each request has its own **Approve** and **Reject** buttons.
4. After approval, return to the sign-in page and use your personal credentials.

Guests select **Request visitor access** on the sign-in page, choose an apartment and date, and enter their name and purpose. They share the confirmation reference with their host. The host opens **Visitor register** to approve or decline the request. On the visit date, gate staff match the guest to the approved request and check them in. The local demo runs on localhost, so guests use the device hosting AptEase.

Run the workflow tests with `.\.venv\Scripts\python.exe -m unittest -v`. These tests use temporary SQLite fixtures. To verify the running MySQL backend, start the app against MySQL and test an overpayment under **Maintenance dues**.

## Share one database over Wi-Fi

On a trusted local network, run AptEase on the laptop that already has the data:

```powershell
.\.venv\Scripts\python.exe app.py --host 0.0.0.0
```

Use the same `--mysql-database` and `--db` arguments if you chose custom names. Find the
host's Wi-Fi IPv4 address with `ipconfig`. Open `http://HOST_IP:8000` in the
browser on the second laptop and sign in with an existing account. The host
can use `http://127.0.0.1:8000` to sign in as a different user. If Windows asks
for firewall access, allow it on Private networks.

Keep AptEase running on the host while both laptops use it. Both browsers save
changes to the host's database. Use this HTTP demo on a trusted LAN.

## Project files

- [app.py](app.py) handles login, permissions, forms, transactions, reports and page rendering.
- [mysql_schema.sql](mysql_schema.sql) and [mysql_payment_trigger.sql](mysql_payment_trigger.sql) define the running app's relational schema.
- [mysql_backend.py](mysql_backend.py) connects to MySQL and imports existing relational records.
- [schema.sql](schema.sql) defines the legacy SQLite schema used by the existing workflow tests.
- [community.py](community.py) contains TinyDB directory storage, vector setup and similarity search.
- [style.css](style.css) styles the responsive web interface.
- [test_app.py](test_app.py) exercises the app over HTTP against a temporary database.

## DBMS viva and PostgreSQL CLI demo

Open [DBMS_DEMO.sql](DBMS_DEMO.sql) in Notepad. It contains PostgreSQL DDL, fictional sample data, five advanced queries, and trigger, function, and role commands. Run it in a fresh PostgreSQL database. The web app uses its own MySQL database.

With PostgreSQL running, open PowerShell and run the following. Replace `postgres` if your local database administrator has a different username. If `psql` is unavailable in PowerShell, use the PostgreSQL SQL Shell or add the installation's `bin` directory to PATH.

```powershell
psql -U postgres -d postgres -c 'CREATE DATABASE aptease_viva;'
psql -U postgres -d aptease_viva -v ON_ERROR_STOP=1 -f DBMS_DEMO.sql
psql -U postgres -d aptease_viva
```

The setup prints five reports using a correlated subquery, a CTE, a recursive CTE, window functions and PostgreSQL full-text search. It then prints `250000` paise from `bill_outstanding(1)`. In the interactive `psql` session, paste these commands individually. The three statements marked as rejected are expected to fail.

```sql
INSERT INTO aptease_demo.payments(bill_id,amount,reference) VALUES (1,250001,'TOO-MUCH'); -- Trigger rejects it.
SELECT aptease_demo.bill_outstanding(1); -- Still 250000.
SET ROLE aptease_demo_billing;
SELECT current_user, aptease_demo.bill_outstanding(1); -- Allowed.
SELECT * FROM aptease_demo.visits; -- Permission denied.
RESET ROLE;
SET ROLE aptease_demo_gate;
SELECT current_user, visitor FROM aptease_demo.visits; -- Allowed.
SELECT * FROM aptease_demo.bill_balances; -- Permission denied.
RESET ROLE;
```

For **NoSQL**, add a contact under **Community directory** and open `aptease.sqlite3.directory.json` locally to show the nested document. For **vector search**, enter `neighbors are too loud` in **Help search** and show the complaints article and its similarity score. Use the web app's existing fictional data or add your own demo records.
