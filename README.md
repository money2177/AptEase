# AptEase Apartment Management System

DBMS mini-project by **Aditi M Hubli (PES1UG24CS652)** and **Fathima Zahra (PES1UG24CS664)**.

AptEase manages a fictional apartment community. The local web app uses Python, server-rendered HTML, CSS and three storage types. The setup below was tested with Python 3.13 on Windows. Confirm any required database products against your course rubric before submission.
 
| Database type | Technology | What it stores |
|---|---|---|
| Relational SQL | SQLite | Accounts, units, occupancies, bills, payments, complaints, bookings and other operational records |
| Document NoSQL | TinyDB | Community directory entries with nested contact details and optional hours |
| Vector database | sqlite-vec in a separate SQLite file | Help articles and their numeric topic vectors. The vector engine retrieves nearest neighbors by cosine distance. |

The stores run in the local app process. Help search uses a small hand-built vocabulary and six topic dimensions. For example, searching for `neighbors are too loud` finds the complaints article. Search covers the included help articles and uses no external embedding service.

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

Open PowerShell in the project folder.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open [AptEase](http://127.0.0.1:8000). First launch creates `aptease.sqlite3`, `aptease.sqlite3.directory.json` and `aptease.sqlite3.vectors.sqlite3`. Existing `cedar.sqlite3` data is reused if the new SQL file is absent, with the companion files named after the database in use. Stop with Ctrl+C. Add `--port 8001` to the launch command if the port is occupied. Add `--db rehearsal.sqlite3` to use a fresh set of three stores for rehearsal. Run one AptEase process per set of database files.

| Staff role | Username | Initial local password |
|---|---|---|
| Administrator | `admin` | `AdminDemo123` |
| Gate staff | `guard` | `GuardDemo123` |

On a fresh database, sign in as admin and add the actual apartments under **Units & residents**. The SQL database starts with the two staff accounts and empty operational records. On an existing database, startup removes the old demo resident and sample service request. Any additional records linked to that account are retained under an archived resident.

1. From the sign-in screen, select **Create a resident account**.
2. Choose **Owner** or **Tenant** and your apartment, then choose a username and a password of at least eight characters.
3. Management verifies the occupant and opens **Units & residents → Resident approvals**. Each request has its own **Approve** and **Reject** buttons.
4. After approval, return to the sign-in page and use your personal credentials.

Guests select **Request visitor access** on the sign-in page, choose an apartment and date, and enter their name and purpose. They share the confirmation reference with their host. The host opens **Visitor register** to approve or decline the request. On the visit date, gate staff match the guest to the approved request and check them in. The local demo runs on localhost, so guests use the device hosting AptEase.

Run the workflow tests with `.\.venv\Scripts\python.exe -m unittest -v`. The tests use temporary databases.

## Project files

- [app.py](app.py) handles login, permissions, forms, transactions, reports and page rendering.
- [schema.sql](schema.sql) defines the tables, keys, indexes, balance view and overpayment trigger.
- [community.py](community.py) contains TinyDB directory storage, vector setup and similarity search.
- [style.css](style.css) styles the responsive web interface.
- [test_app.py](test_app.py) exercises the app over HTTP against a temporary database.

## DBMS viva and PostgreSQL CLI demo

Open [DBMS_DEMO.sql](DBMS_DEMO.sql) in Notepad. It contains the full PostgreSQL DDL, fictional sample data with INSERT, UPDATE and DELETE, five advanced queries, and the trigger, stored function and role commands. Run it in a fresh demo database. The web app continues to use its own SQLite file, so the PostgreSQL demo data is independent of the web app data.

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
