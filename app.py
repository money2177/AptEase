import argparse
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from hashlib import scrypt
from hmac import compare_digest
from html import escape
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import sqlite3
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from community import CommunityStores

ROOT = Path(__file__).resolve().parent
ADMIN, RESIDENT, GUARD = "admin", "resident", "guard"
COMPLAINT_CATEGORIES = ("Noise", "Cleanliness", "Security", "Shared spaces", "Other")
REQUEST_STATUSES = ("Open", "In progress", "Resolved")
PAGES = {
    "dashboard": ("Overview", (ADMIN, RESIDENT, GUARD)),
    "units": ("Units & residents", (ADMIN,)),
    "billing": ("Maintenance dues", (ADMIN, RESIDENT)),
    "tickets": ("Service requests", (ADMIN, RESIDENT)),
    "complaints": ("Complaints", (ADMIN, RESIDENT)),
    "visits": ("Visitor register", (ADMIN, GUARD, RESIDENT)),
    "parking": ("Parking", (ADMIN, RESIDENT)),
    "bookings": ("Facilities", (ADMIN, RESIDENT)),
    "notices": ("Notice board", (ADMIN, RESIDENT, GUARD)),
    "directory": ("Community directory", (ADMIN, RESIDENT, GUARD)),
    "help": ("Help search", (ADMIN, RESIDENT, GUARD)),
}
UNIT = "u.block || '-' || u.number"


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ":" + digest.hex()


def initialize(path):
    with closing(connect(path)) as db, db:
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        db.executemany("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,?)", [
            ("Community Manager", "admin", password_hash("AdminDemo123"), ADMIN),
            ("Ananya Rao", "resident", password_hash("ResidentDemo123"), RESIDENT),
            ("Front Gate", "guard", password_hash("GuardDemo123"), GUARD),
        ])
        db.executemany("INSERT INTO units(block,number,bedrooms) VALUES (?,?,?)",
                       [("A","101",2), ("A","102",3), ("B","201",2), ("B","202",3)])
        db.execute("INSERT INTO occupancies(unit_id,user_id,kind,start_date) VALUES (1,2,'Owner',?)",
                   (date.today().isoformat(),))
        db.execute("INSERT INTO bills(unit_id,period,amount,due_date) VALUES (1,?,350000,?)",
                   (date.today().strftime("%Y-%m"), date.today().replace(day=28).isoformat()))
        db.execute("INSERT INTO tickets(occupancy_id,subject,description) VALUES (1,?,?)",
                   ("Corridor light", "The light outside A-101 needs replacement."))
        db.executemany("INSERT INTO parking(slot,unit_id,vehicle) VALUES (?,?,?)",
                       [("P-01",1,"DEMO-101"), ("P-02",None,None), ("P-03",None,None)])
        db.executemany("INSERT INTO facilities(name) VALUES (?)",
                       [("Multipurpose Hall",), ("Badminton Court",)])
        db.execute("INSERT INTO notices(title,body) VALUES (?,?)",
                   ("Welcome to AptEase", "Use the portal to book facilities, request maintenance or file a complaint."))


def money(paise):
    return f"₹{Decimal(paise) / 100:,.2f}"


def e(value):
    return escape(str(value), quote=True)


def field(name, label, kind="text"):
    if isinstance(kind, (list, tuple)):
        options = "".join(f'<option value="{e(key)}">{e(value)}</option>' for key, value in kind)
        control = f'<select name="{name}" required>{options}</select>'
    elif kind == "textarea":
        control = f'<textarea name="{name}" maxlength="1500" required></textarea>'
    else:
        control = f'<input name="{name}" type="{kind}" maxlength="150" required>'
    return f'<label>{e(label)}{control}</label>'


def form(token, action, title, button, *fields):
    return (f'<section class="card"><h2>{e(title)}</h2><form method="post">'
            f'<input type="hidden" name="token" value="{e(token)}">'
            f'<input type="hidden" name="action" value="{e(action)}">'
            f'<div class="fields">{"".join(fields)}</div><button>{e(button)}</button></form></section>')


def table(title, headers, rows):
    head = "".join(f"<th scope='col'>{e(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{e(x if x is not None else '—')}</td>" for x in row)
                   + "</tr>" for row in rows)
    if not body:
        body = f'<tr><td colspan="{len(headers)}">No records yet.</td></tr>'
    return (f'<section class="card"><h2>{e(title)}</h2><div class="scroll"><table>'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></section>')


def directory_content(stores, user, token):
    contacts = stores.directory()
    content = table("Community contacts", ("Name", "Category", "Contact", "Hours"),
                    [(row["name"], row["category"], row["contact"]["channel"], row["contact"].get("hours"))
                     for row in contacts])
    if user["role"] == ADMIN:
        content += form(token,"directory_add","Add a contact","Add contact",field("name","Name"),
                        field("category","Category"),field("channel","Public contact details"),
                        '<label>Hours (optional)<input name="hours" maxlength="150"></label>')
        if contacts:
            content += form(token,"directory_remove","Remove a contact","Remove contact",
                            field("contact","Contact",[(row.doc_id,f'{row["name"]} · {row["category"]}')
                                                       for row in contacts]))
    return content


def help_content(stores, query):
    content = f"""<section class="card"><form method="get" action="/help">
      <div class="fields"><label>What do you need help with?
      <input name="q" type="search" maxlength="150" value="{e(query)}"
             placeholder="Example: neighbors are too loud" required></label></div>
      <button>Search help articles</button></form></section>"""
    if not query:
        return content
    matches = stores.search_help(query)
    if not matches:
        return content + '<p role="status">No matching help articles. Try words like dues, repairs, guests or parking.</p>'
    return content + table("Matching help articles", ("Article", "Instructions", "Similarity"), matches)


def page_content(db, page, user, token):
    role = user["role"]
    admin = role == ADMIN
    resident = role == RESIDENT
    occupant = db.execute("SELECT * FROM occupancies WHERE user_id=? AND end_date IS NULL",
                          (user["id"],)).fetchone()
    unit_id = occupant["unit_id"] if occupant else None
    unit_options = db.execute(f"SELECT u.id,{UNIT} FROM units u ORDER BY u.block,u.number").fetchall()
    unit = field("unit", "Apartment", list(map(tuple, unit_options)))

    def F(action, title, button, *fields):
        return form(token, action, title, button, *fields)

    if page == "dashboard":
        if admin:
            units, occupied, outstanding, open_tickets = db.execute("""
              SELECT (SELECT COUNT(*) FROM units),
                     (SELECT COUNT(DISTINCT unit_id) FROM occupancies WHERE end_date IS NULL),
                     (SELECT COALESCE(SUM(balance),0) FROM bill_balances),
                     (SELECT COUNT(*) FROM tickets WHERE status <> 'Resolved')
            """).fetchone()
            metrics = [("Total apartments", units), ("Occupied apartments", occupied),
                       ("Outstanding dues", money(outstanding)), ("Active requests", open_tickets)]
        elif resident:
            balance = db.execute("SELECT COALESCE(SUM(balance),0) FROM bill_balances WHERE unit_id=?",
                                 (unit_id,)).fetchone()[0]
            count = db.execute("""SELECT COUNT(*) FROM tickets t JOIN occupancies o ON o.id=t.occupancy_id
                                  WHERE o.user_id=? AND t.status<>'Resolved'""", (user["id"],)).fetchone()[0]
            metrics = [("Outstanding dues", money(balance)), ("My active requests", count)]
        else:
            count = db.execute("SELECT COUNT(*) FROM visits WHERE departed_at IS NULL").fetchone()[0]
            metrics = [("Visitors on site", count)]
        if admin:
            count = db.execute("SELECT COUNT(*) FROM complaints WHERE status <> 'Resolved'").fetchone()[0]
            metrics.append(("Active complaints", count))
        elif resident:
            count = db.execute("""SELECT COUNT(*) FROM complaints c JOIN occupancies o ON o.id=c.occupancy_id
                                  WHERE o.user_id=? AND c.status<>'Resolved'""", (user["id"],)).fetchone()[0]
            metrics.append(("My active complaints", count))
        stats = "".join(f'<div class="metric"><span>{e(label)}</span><strong>{e(value)}</strong></div>'
                        for label, value in metrics)
        return f'<div class="metrics">{stats}</div>' + table("Latest notices", ("Title","Message"), db.execute(
            "SELECT title,body FROM notices ORDER BY id DESC LIMIT 3"))

    if page == "units":
        rows = db.execute(f"""SELECT {UNIT},u.bedrooms,COUNT(o.id) FROM units u
            LEFT JOIN occupancies o ON o.unit_id=u.id AND o.end_date IS NULL
            GROUP BY u.id ORDER BY u.block,u.number""")
        history = db.execute(f"""SELECT o.id,p.name,p.username,{UNIT},o.kind,o.start_date,o.end_date
           FROM occupancies o JOIN units u ON u.id=o.unit_id JOIN users p ON p.id=o.user_id
           ORDER BY o.id DESC""")
        residents = list(map(tuple, db.execute("""SELECT p.id,p.name || ' (' || p.username || ')' FROM users p
          WHERE role='resident' AND NOT EXISTS
          (SELECT 1 FROM occupancies o WHERE o.user_id=p.id AND o.end_date IS NULL) ORDER BY p.name""")))
        active = list(map(tuple, db.execute("""SELECT o.id,p.name || ' (' || p.username || ')'
          FROM occupancies o JOIN users p ON p.id=o.user_id WHERE o.end_date IS NULL ORDER BY p.name""")))
        kind = field("kind","Occupancy type",[("Owner","Owner"),("Tenant","Tenant")])
        forms = F("unit","Add an apartment","Add apartment",field("block","Block"),
                  field("number","Apartment number"),field("bedrooms","Bedrooms","number"))
        if unit_options:
            forms += F("register","Register and move in","Register resident",unit,kind,field("name","Full name"),
                       field("username","Username"),field("password","Initial password (10+ characters)","password"))
            if residents:
                forms += F("movein","Move in an existing resident","Move in",unit,kind,
                           field("user","Resident account",residents))
        if active:
            forms += F("moveout","End an occupancy","Move out",field("occupancy","Resident",active))
        return (table("Apartment inventory",("Apartment","Bedrooms","Current residents"),rows)
                + table("Occupancy history",("ID","Name","Username","Apartment","Type","Start date","End date"),history) + forms)

    if page == "billing":
        scope, params = ("", ()) if admin else (" WHERE b.unit_id=?", (unit_id,))
        balances = db.execute(f"""SELECT b.id,{UNIT} AS apartment,b.period,b.amount,b.paid,b.balance,b.due_date
          FROM bill_balances b JOIN units u ON u.id=b.unit_id{scope} ORDER BY b.period DESC,b.id DESC""", params).fetchall()
        ledger = db.execute(f"""SELECT p.id,p.bill_id,{UNIT},p.amount,p.reference,p.paid_at
          FROM payments p JOIN bills b ON b.id=p.bill_id JOIN units u ON u.id=b.unit_id{scope}
          ORDER BY p.id DESC""", params)
        content = table("Bills and balances",("Bill","Apartment","Month","Billed","Paid","Balance","Due","Status"),
                        [(r[0],r[1],r[2],money(r[3]),money(r[4]),money(r[5]),r[6],
                          "Paid" if not r[5] else "Overdue" if r[6]<date.today().isoformat() else "Due")
                         for r in balances])
        content += table("Payment ledger",("Receipt","Bill","Apartment","Amount","Reference","Recorded (UTC)"),
                         [(r[0],r[1],r[2],money(r[3]),r[4],r[5]) for r in ledger])
        if admin and unit_options:
            content += F("bill","Issue a monthly bill","Issue bill",unit,field("period","Billing month (YYYY-MM)"),
                         field("amount","Amount in rupees"),field("due","Due date","date"))
            unpaid = [(r[0],f"#{r[0]} · {r[1]} · {r[2]} · {money(r[5])} due") for r in balances if r[5]]
            if unpaid:
                content += F("payment","Record a payment","Record payment",field("bill","Bill",unpaid),
                             field("amount","Amount in rupees"),field("reference","Receipt or transfer reference"))
        return content

    if page == "tickets":
        scope, params = ("", ()) if admin else (" WHERE o.user_id=?", (user["id"],))
        rows = db.execute(f"""SELECT t.id,{UNIT},p.name,t.subject,t.description,t.status,t.created_at FROM tickets t
           JOIN occupancies o ON o.id=t.occupancy_id JOIN units u ON u.id=o.unit_id
           JOIN users p ON p.id=o.user_id{scope} ORDER BY t.id DESC""", params).fetchall()
        content = table("Maintenance requests",("ID","Apartment","Resident","Subject","Details","Status","Opened (UTC)"),rows)
        if admin and rows:
            content += F("status","Update a service request","Save status",field("ticket","Request",[(r[0],r[3]) for r in rows]),
                         field("status","Status",[(x,x) for x in REQUEST_STATUSES]))
        if resident and occupant:
            content += F("ticket","Submit a service request","Submit request",field("subject","Subject"),
                         field("description","Details","textarea"))
        return content

    if page == "complaints":
        scope, params = ("", ()) if admin else (" WHERE o.user_id=?", (user["id"],))
        rows = db.execute(f"""SELECT c.id,{UNIT},p.name,c.category,c.subject,c.description,
                  c.status,c.response,c.updated_at FROM complaints c
                  JOIN occupancies o ON o.id=c.occupancy_id JOIN units u ON u.id=o.unit_id
                  JOIN users p ON p.id=o.user_id{scope} ORDER BY c.id DESC""", params).fetchall()
        content = table("Complaint register",("ID","Apartment","Resident","Category","Subject",
                        "Details","Status","Management response","Updated (UTC)"),rows)
        if resident and occupant:
            content += F("complaint","File a complaint","Submit complaint",
                         field("category","Category",[(x,x) for x in COMPLAINT_CATEGORIES]),
                         field("subject","Subject"),field("description","Details","textarea"))
        if admin and rows:
            content += F("complaint_response","Respond to a complaint","Save response",
                         field("complaint","Complaint",[(r[0],f"#{r[0]} · {r[4]}") for r in rows]),
                         field("status","Status",[(x,x) for x in REQUEST_STATUSES]),
                         field("response","Response visible to resident","textarea"))
        return content

    if page == "visits":
        scope, params = (" WHERE v.unit_id=?", (unit_id,)) if resident else ("", ())
        rows = db.execute(f"""SELECT v.id,{UNIT},v.visitor,v.purpose,v.arrived_at,v.departed_at FROM visits v
                           JOIN units u ON u.id=v.unit_id{scope} ORDER BY v.id DESC""", params).fetchall()
        content = table("Gate activity",("ID","Apartment","Visitor","Purpose","Arrival (UTC)","Departure (UTC)"),rows)
        if not resident and unit_options:
            content += F("arrival","Check in a visitor","Check in",unit,field("visitor","Visitor name"),field("purpose","Purpose"))
            active = [(r[0],f"{r[2]} · {r[1]}") for r in rows if not r[5]]
            if active:
                content += F("departure","Check out a visitor","Check out",field("visit","Visitor",active))
        return content

    if page == "parking":
        scope, params = ("", ()) if admin else (" WHERE p.unit_id=?", (unit_id,))
        rows = db.execute(f"""SELECT p.id,p.slot,{UNIT},p.vehicle FROM parking p
           LEFT JOIN units u ON u.id=p.unit_id{scope} ORDER BY p.slot""", params).fetchall()
        content = table("Parking allocation",("Slot","Apartment","Vehicle"),[tuple(r)[1:] for r in rows])
        if admin:
            content += F("slot","Add a parking slot","Add slot",field("slot","Slot identifier"))
            vacant = [(r[0],r[1]) for r in rows if not r[3]]
            assigned = [(r[0],r[1]) for r in rows if r[3]]
            if vacant and unit_options:
                content += F("assign","Allocate a slot","Allocate",field("slot","Vacant slot",vacant),unit,field("vehicle","Vehicle registration"))
            if assigned:
                content += F("release","Release a slot","Release",field("slot","Allocated slot",assigned))
        return content

    if page == "bookings":
        facilities = list(map(tuple, db.execute("SELECT id,name FROM facilities ORDER BY name")))
        schedule = db.execute("""SELECT f.name,b.day,printf('%02d:00',b.hour) FROM bookings b
                    JOIN facilities f ON f.id=b.facility_id WHERE b.day>=? ORDER BY b.day,b.hour""",
                    (date.today().isoformat(),))
        scope, params = ("", ()) if admin else (" WHERE o.user_id=?", (user["id"],))
        rows = db.execute(f"""SELECT b.id,f.name,b.day,b.hour,{UNIT}
                   FROM bookings b JOIN facilities f ON f.id=b.facility_id
                   JOIN occupancies o ON o.id=b.occupancy_id JOIN units u ON u.id=o.unit_id
                   {scope} ORDER BY b.day DESC,b.hour DESC""", params).fetchall()
        content = table("Upcoming reserved slots",("Facility","Date","Start"),schedule)
        content += table("Booking history",("ID","Facility","Date","Start","Apartment"),
                         [(r[0],r[1],r[2],f"{r[3]:02d}:00",r[4]) for r in rows])
        if admin:
            content += F("facility","Add a facility","Add facility",field("name","Facility name"))
        if resident and occupant and facilities:
            content += F("booking","Reserve a one-hour slot","Reserve",
                         field("facility","Facility",facilities),field("day","Date","date"),
                         field("hour","Start time",[(h,f"{h:02d}:00") for h in range(8,21)]))
        now = datetime.now()
        future = [(r[0],f"{r[1]} · {r[2]} · {r[3]:02d}:00") for r in rows
                  if datetime.combine(date.fromisoformat(r[2]), datetime.min.time()).replace(hour=r[3]) > now]
        if future:
            content += F("cancel","Cancel a reservation","Cancel booking",field("booking","Reservation",future))
        return content

    content = table("Community announcements",("Title","Message","Published (UTC)"),db.execute(
        "SELECT title,body,created_at FROM notices ORDER BY id DESC"))
    if admin:
        content += F("notice","Publish a notice","Publish notice",field("title","Title"),field("body","Message","textarea"))
    return content


ACTION_PAGE_ROLE = {
    "unit": ("units", ADMIN), "register": ("units", ADMIN), "movein": ("units", ADMIN), "moveout": ("units", ADMIN),
    "bill": ("billing", ADMIN), "payment": ("billing", ADMIN),
    "ticket": ("tickets", RESIDENT), "status": ("tickets", ADMIN),
    "complaint": ("complaints", RESIDENT), "complaint_response": ("complaints", ADMIN),
    "arrival": ("visits", ADMIN, GUARD), "departure": ("visits", ADMIN, GUARD),
    "slot": ("parking", ADMIN), "assign": ("parking", ADMIN), "release": ("parking", ADMIN),
    "facility": ("bookings", ADMIN), "booking": ("bookings", RESIDENT), "cancel": ("bookings", ADMIN, RESIDENT),
    "notice": ("notices", ADMIN),
    "directory_add": ("directory", ADMIN), "directory_remove": ("directory", ADMIN),
}


def input_value(data, key, limit=150, required=True):
    result = data.get(key, "").strip()
    if (required and not result) or len(result) > limit:
        raise ValueError(f"Enter a valid {key} (up to {limit} characters).")
    return result


def apply_directory_action(stores, action, data):
    if action == "directory_add":
        stores.add_contact(input_value(data,"name"),input_value(data,"category"),
                           input_value(data,"channel"),input_value(data,"hours",required=False))
    else:
        contact = input_value(data,"contact",10)
        if not contact.isascii() or not contact.isdecimal():
            raise ValueError("Select an existing contact.")
        stores.remove_contact(int(contact))


def apply_action(db, action, data, user):
    def value(key, limit=150):
        return input_value(data, key, limit)

    def number(key, low=1, high=2**31-1):
        raw = value(key, 10)
        if not raw.isascii() or not raw.isdecimal() or not low <= int(raw) <= high:
            raise ValueError(f"Enter a valid {key}.")
        return int(raw)

    def choice(key, choices):
        selected = value(key)
        if selected not in choices:
            raise ValueError(f"Choose a valid {key}.")
        return selected

    def amount():
        raw = value("amount", 12)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", raw):
            raise ValueError("Enter a positive rupee amount with up to two decimal places.")
        paise = int(Decimal(raw) * 100)
        if not 0 < paise <= 100_000_000:
            raise ValueError("Amount must be between ₹0.01 and ₹10,00,000.")
        return paise

    def calendar_date(key):
        raw = value(key, 10)
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
            raise ValueError("Choose a valid date.")
        return date.fromisoformat(raw)

    def occupancy():
        record = db.execute("SELECT id FROM occupancies WHERE user_id=? AND end_date IS NULL",
                            (user["id"],)).fetchone()
        if not record:
            raise ValueError("A current apartment occupancy is required.")
        return record[0]

    def change(sql, params):
        if db.execute(sql, params).rowcount != 1:
            raise ValueError("This record is unavailable or has already changed.")

    today = date.today().isoformat()
    if action == "unit":
        db.execute("INSERT INTO units(block,number,bedrooms) VALUES (?,?,?)",
                   (value("block",20).upper(),value("number",20).upper(),number("bedrooms",1,8)))
    elif action in ("register","movein"):
        target = number("unit")
        kind = choice("kind",("Owner","Tenant"))
        if action == "register":
            password = value("password")
            username = value("username",40).lower()
            if len(password) < 10 or not re.fullmatch(r"[a-z0-9._-]{3,40}",username):
                raise ValueError("Use a password of 10+ characters and a username of 3–40 letters, digits, dots, underscores or hyphens.")
            person = db.execute("INSERT INTO users(name,username,password_hash,role) VALUES (?,?,?,?)",
                                (value("name"),username,password_hash(password),RESIDENT)).lastrowid
        else:
            person = number("user")
        change("""INSERT INTO occupancies(unit_id,user_id,kind,start_date)
                  SELECT ?,id,?,? FROM users WHERE id=? AND role='resident'""", (target,kind,today,person))
    elif action == "moveout":
        change("UPDATE occupancies SET end_date=? WHERE id=? AND end_date IS NULL",(today,number("occupancy")))
    elif action == "bill":
        period = value("period",7)
        if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])",period) or period.startswith("0000"):
            raise ValueError("Use a billing month in YYYY-MM format.")
        db.execute("INSERT INTO bills(unit_id,period,amount,due_date) VALUES (?,?,?,?)",
                   (number("unit"),period,amount(),calendar_date("due").isoformat()))
    elif action == "payment":
        db.execute("INSERT INTO payments(bill_id,amount,reference) VALUES (?,?,?)",
                   (number("bill"),amount(),value("reference").upper()))
    elif action == "ticket":
        db.execute("INSERT INTO tickets(occupancy_id,subject,description) VALUES (?,?,?)",
                   (occupancy(),value("subject"),value("description",1500)))
    elif action == "status":
        change("UPDATE tickets SET status=? WHERE id=?",
               (choice("status",REQUEST_STATUSES),number("ticket")))
    elif action == "complaint":
        db.execute("INSERT INTO complaints(occupancy_id,category,subject,description) VALUES (?,?,?,?)",
                   (occupancy(),choice("category",COMPLAINT_CATEGORIES),value("subject"),value("description",1500)))
    elif action == "complaint_response":
        change("""UPDATE complaints SET status=?,response=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
               (choice("status",REQUEST_STATUSES),value("response",1500),number("complaint")))
    elif action == "arrival":
        db.execute("INSERT INTO visits(unit_id,visitor,purpose) VALUES (?,?,?)",
                   (number("unit"),value("visitor"),value("purpose")))
    elif action == "departure":
        change("UPDATE visits SET departed_at=CURRENT_TIMESTAMP WHERE id=? AND departed_at IS NULL",(number("visit"),))
    elif action == "slot":
        db.execute("INSERT INTO parking(slot) VALUES (?)",(value("slot").upper(),))
    elif action == "assign":
        change("UPDATE parking SET unit_id=?,vehicle=? WHERE id=? AND unit_id IS NULL",
               (number("unit"),value("vehicle").upper(),number("slot")))
    elif action == "release":
        change("UPDATE parking SET unit_id=NULL,vehicle=NULL WHERE id=? AND unit_id IS NOT NULL",(number("slot"),))
    elif action == "facility":
        db.execute("INSERT INTO facilities(name) VALUES (?)",(value("name"),))
    elif action == "booking":
        day = calendar_date("day")
        hour = number("hour",8,20)
        if datetime.combine(day,datetime.min.time()).replace(hour=hour) <= datetime.now():
            raise ValueError("Choose a future start time.")
        db.execute("INSERT INTO bookings(facility_id,occupancy_id,day,hour) VALUES (?,?,?,?)",
                   (number("facility"),occupancy(),day.isoformat(),hour))
    elif action == "cancel":
        row = db.execute("""SELECT b.day,b.hour,o.user_id FROM bookings b
                            JOIN occupancies o ON o.id=b.occupancy_id WHERE b.id=?""",(number("booking"),)).fetchone()
        if not row or (user["role"] != ADMIN and row[2] != user["id"]):
            raise ValueError("This booking is unavailable.")
        if datetime.combine(date.fromisoformat(row[0]),datetime.min.time()).replace(hour=row[1]) <= datetime.now():
            raise ValueError("Only future bookings can be cancelled.")
        change("DELETE FROM bookings WHERE id=?",(number("booking"),))
    elif action == "notice":
        db.execute("INSERT INTO notices(title,body) VALUES (?,?)",(value("title"),value("body",1500)))


class Portal(BaseHTTPRequestHandler):
    sessions = {}
    session_lock = Lock()
    lifetime = 8 * 60 * 60

    def __init__(self, *args, database, stores, **kwargs):
        self.database = database
        self.stores = stores
        super().__init__(*args, **kwargs)

    def send(self, status, body=b"", content_type="text/html; charset=utf-8", **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        for key, val in headers.items():
            self.send_header(key.replace("_","-"),val)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, target, cookie=None):
        extra = {"Set_Cookie": cookie} if cookie else {}
        self.send(303, Location=target, **extra)

    def session(self):
        try:
            item = SimpleCookie(self.headers.get("Cookie","")).get("cedar")
        except CookieError:
            item = None
        sid = item.value if item else ""
        with self.session_lock:
            session = self.sessions.get(sid)
            if session and session[2] > monotonic():
                return sid, session
            self.sessions.pop(sid, None)
        return sid, None

    def layout(self, title, content, user=None, token="", page="", message="", error=False, status=200, cookie=None):
        note = f'<p class="message {"error" if error else ""}" role="status">{e(message)}</p>' if message else ""
        if user:
            links = "".join(f'<a href="/{key}" {"aria-current=page" if page==key else ""}>{e(label)}</a>'
                            for key,(label,roles) in PAGES.items() if user["role"] in roles)
            frame = f"""<aside class="sidebar"><div class="brand"><b>AptEase</b><span>Apartment portal</span></div>
              <nav aria-label="Main navigation">{links}</nav><div class="account"><b>{e(user["name"])}</b>
              <span>{e(user["role"].title())}</span><form method="post" action="/logout">
              <input type="hidden" name="token" value="{e(token)}"><button class="quiet">Sign out</button></form></div></aside>
              <main><header><h1>{e(title)}</h1></header>{note}{content}</main>"""
        else:
            frame = f'<main class="signin"><header><span>APARTMENT MANAGEMENT SYSTEM</span><h1>AptEase</h1></header>{note}{content}</main>'
        doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>{e(title)} · AptEase</title><link rel="stylesheet" href="/style.css"></head>
            <body>{frame}</body></html>"""
        extra = {"Set_Cookie":cookie} if cookie else {}
        self.send(status,doc.encode(),**extra)

    def new_session(self, user_id=None):
        sid = secrets.token_urlsafe(32)
        token = secrets.token_urlsafe(32)
        with self.session_lock:
            now = monotonic()
            expired = [key for key, session in self.sessions.items() if session[2] <= now]
            for key in expired:
                del self.sessions[key]
            self.sessions[sid] = (user_id,token,now+self.lifetime)
        return token, f"cedar={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={self.lifetime}"

    def login_page(self, token, message="", cookie=None):
        self.layout("Sign in",form(token,"login","Sign in","Sign in",field("username","Username"),
                    field("password","Password","password")), message=message,error=bool(message),cookie=cookie)

    def show_page(self, db, user, token, path, message="", error=False, query=""):
        try:
            if path == "directory":
                content = directory_content(self.stores,user,token)
            elif path == "help":
                content = help_content(self.stores,query)
            else:
                content = page_content(db,path,user,token)
        except (OSError, ValueError, sqlite3.OperationalError):
            self.send(503,b"Data store temporarily unavailable.","text/plain; charset=utf-8")
            return
        self.layout(PAGES[path][0],content,user,token,path,message,error,422 if error else 200)

    def do_GET(self):
        target = urlsplit(self.path)
        path = target.path.strip("/")
        if path == "style.css":
            self.send(200,(ROOT / "style.css").read_bytes(),"text/css; charset=utf-8")
            return
        _, session = self.session()
        if not session or session[0] is None:
            if path not in ("","login"):
                self.redirect("/login")
            elif session:
                self.login_page(session[1])
            else:
                token,cookie = self.new_session()
                self.login_page(token,cookie=cookie)
            return
        if path in ("","login"):
            self.redirect("/dashboard")
            return
        with closing(connect(self.database)) as db:
            user = db.execute("SELECT * FROM users WHERE id=?",(session[0],)).fetchone()
            if not user:
                self.redirect("/login","cedar=; Path=/; Max-Age=0")
            elif path not in PAGES or user["role"] not in PAGES[path][1]:
                self.send(404,b"Page unavailable","text/plain; charset=utf-8")
            else:
                query = ""
                if path == "help":
                    try:
                        query = parse_qs(target.query,max_num_fields=10).get("q",[""])[0].strip()
                        if len(query) > 150:
                            raise ValueError
                    except ValueError:
                        self.show_page(db,user,session[1],path,"Enter a search of up to 150 characters.",True)
                        return
                self.show_page(db,user,session[1],path,query=query)

    def do_POST(self):
        path = urlsplit(self.path).path.strip("/")
        try:
            size = int(self.headers.get("Content-Length","0"))
            if not 0 < size <= 16_384:
                raise ValueError
            data = {k:v[0] for k,v in parse_qs(self.rfile.read(size).decode(),max_num_fields=20).items()}
        except (ValueError, UnicodeError):
            self.send(400,b"Invalid request","text/plain; charset=utf-8")
            return
        sid, session = self.session()
        token = data.get("token","")
        if not session or not token.isascii() or not compare_digest(token,session[1]):
            self.send(403,b"Invalid or expired form. Reload the page.","text/plain; charset=utf-8")
            return
        with closing(connect(self.database)) as db:
            if session[0] is None:
                if path not in ("","login"):
                    self.redirect("/login")
                    return
                username = data.get("username","").strip().lower()
                password = data.get("password","").strip()
                account = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
                stored = account["password_hash"] if account else "0"*32 + ":" + "0"*128
                if len(password) <= 150 and compare_digest(password_hash(password,stored.split(":")[0]),stored):
                    with self.session_lock:
                        self.sessions.pop(sid,None)
                    _, cookie = self.new_session(account["id"])
                    self.redirect("/dashboard",cookie)
                else:
                    self.login_page(session[1],"Check your username and password.")
                return
            if path == "logout":
                with self.session_lock:
                    self.sessions.pop(sid,None)
                self.redirect("/login","cedar=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                return
            user = db.execute("SELECT * FROM users WHERE id=?",(session[0],)).fetchone()
            action = data.get("action","")
            rule = ACTION_PAGE_ROLE.get(action)
            if not user or not rule or path != rule[0] or user["role"] not in rule[1:]:
                self.send(403,b"Action unavailable","text/plain; charset=utf-8")
                return
            try:
                if path == "directory":
                    apply_directory_action(self.stores,action,data)
                else:
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        apply_action(db,action,data,user)
            except (ValueError, InvalidOperation) as ex:
                self.show_page(db,user,session[1],path,str(ex),True)
            except sqlite3.IntegrityError as ex:
                reason = str(ex)
                if reason == "Payment exceeds outstanding balance":
                    message = reason + "."
                elif "UNIQUE" in reason:
                    message = "A conflicting record already exists. Check the existing records or choose a different value."
                else:
                    message = "A related record is unavailable or a database rule was violated."
                self.show_page(db,user,session[1],path,message,True)
            except (sqlite3.OperationalError, OSError):
                self.send(503,b"Database temporarily unavailable. Reload and try again.","text/plain; charset=utf-8")
            else:
                self.redirect("/" + path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AptEase apartment management demo")
    legacy_database = ROOT / "cedar.sqlite3"
    current_database = ROOT / "aptease.sqlite3"
    default_database = legacy_database if legacy_database.exists() and not current_database.exists() else current_database
    parser.add_argument("--db",type=Path,default=default_database)
    parser.add_argument("--port",type=int,default=8000)
    args = parser.parse_args()
    initialize(args.db)
    with CommunityStores(args.db) as stores, ThreadingHTTPServer(
        ("127.0.0.1",args.port),partial(Portal,database=args.db,stores=stores)
    ) as server:
        print(f"AptEase is running at http://127.0.0.1:{server.server_port}",flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
