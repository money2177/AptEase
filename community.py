"""Persistent non-relational stores used by AptEase's local server."""

from contextlib import ExitStack, closing
import json
import os
import re
import sqlite3
from tempfile import NamedTemporaryFile
from threading import Lock

import sqlite_vec
from tinydb import Query, TinyDB
from tinydb.storages import Storage


class AtomicJSONStorage(Storage):
    def __init__(self, path):
        self.path = path

    def read(self):
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return None

    def write(self, data):
        output = NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False)
        temporary = self.path.with_name(os.path.basename(output.name))
        try:
            with output:
                json.dump(data, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


# Each coordinate describes a concept. Aliases such as "broken" and "repair"
# activate the same coordinate even when their literal words differ.
TOPICS = (
    ("dues", "bill", "bills", "pay", "payment", "payments", "balance", "receipt", "fee", "fees"),
    ("repair", "broken", "leak", "leaking", "maintenance", "fix", "plumbing", "electricity"),
    ("complaint", "complaints", "noise", "noisy", "loud", "disturbance", "cleanliness"),
    ("visitor", "visitors", "guest", "guests", "delivery", "gate", "checkin"),
    ("parking", "vehicle", "car", "motorcycle", "garage", "slot"),
    ("booking", "book", "reserve", "reservation", "facility", "facilities", "court", "hall"),
)
ARTICLES = (
    ("Check your maintenance bill", "Open Maintenance dues to see bills, receipts and outstanding balances. Management records payments."),
    ("Request a repair", "Open Service requests, describe the fault and submit it. Check the page later for a status update."),
    ("File a community complaint", "Open Complaints, choose a category and write what happened. The management response appears on the same page."),
    ("Find an apartment visitor", "Open Visitor register to see arrivals for your apartment. Gate staff handle check-in and check-out."),
    ("Check your parking allocation", "Open Parking to find your apartment’s allocated spaces. Management assigns and releases spaces."),
    ("Book a shared facility", "Open Facilities, choose a one-hour start time and reserve it. Future reservations can be cancelled there."),
)


class CommunityStores(ExitStack):
    def __init__(self, sql_path):
        super().__init__()
        self.lock = Lock()
        self.document_path = sql_path.with_suffix(sql_path.suffix + ".directory.json")
        self.vector_path = sql_path.with_suffix(sql_path.suffix + ".vectors.sqlite3")

    def __enter__(self):
        super().__enter__()
        try:
            documents = self.enter_context(TinyDB(self.document_path, storage=AtomicJSONStorage))
            self.contacts = documents.table("contacts")
            if documents.get(doc_id=1) is None:
                if not len(self.contacts):
                    self.contacts.insert_multiple([
                        {"name": "Management office", "category": "Administration",
                         "contact": {"channel": "Visit the lobby desk", "hours": "Weekdays, 09:00–17:00"}},
                        {"name": "Front gate", "category": "Security",
                         "contact": {"channel": "Visit the gate desk"}},
                    ])
                documents.insert({"directory_initialized": True})
            self.vectors = self.enter_context(closing(sqlite3.connect(
                self.vector_path, check_same_thread=False,
            )))
            self.vectors.enable_load_extension(True)
            try:
                sqlite_vec.load(self.vectors)
            finally:
                self.vectors.enable_load_extension(False)
            with self.vectors:
                self.vectors.execute(f"""CREATE VIRTUAL TABLE IF NOT EXISTS help_articles USING vec0(
                    embedding FLOAT[{len(TOPICS)}] distance_metric=cosine, +title TEXT, +body TEXT
                )""")
                self.vectors.execute("DELETE FROM help_articles")
                self.vectors.executemany(
                    "INSERT INTO help_articles(rowid,embedding,title,body) VALUES (?,?,?,?)",
                    [
                        (index + 1, sqlite_vec.serialize_float32(
                            [float(index == topic) for topic in range(len(TOPICS))]
                        ), title, body)
                        for index, (title, body) in enumerate(ARTICLES)
                    ],
                )
        except BaseException:
            self.close()
            raise
        return self

    def directory(self):
        with self.lock:
            return sorted(self.contacts.all(), key=lambda row: row["name"].casefold())

    def add_contact(self, name, category, channel, hours):
        contact = {"channel": channel}
        if hours:
            contact["hours"] = hours
        with self.lock:
            entry = Query()
            if self.contacts.contains((entry.name == name) & (entry.category == category)):
                raise ValueError("This directory entry already exists.")
            self.contacts.insert({"name": name, "category": category, "contact": contact})

    def remove_contact(self, entry_id):
        with self.lock:
            if not self.contacts.contains(doc_id=entry_id):
                raise ValueError("This directory entry is unavailable.")
            self.contacts.remove(doc_ids=[entry_id])

    def search_help(self, phrase):
        words = set(re.findall(r"[a-z]+", phrase.lower()))
        vector = [float(len(words.intersection(aliases))) for aliases in TOPICS]
        if not any(vector):
            return []
        with self.lock:
            results = self.vectors.execute("""SELECT title,body,distance FROM help_articles
                WHERE embedding MATCH ? AND k=3 ORDER BY distance""",
                (sqlite_vec.serialize_float32(vector),)).fetchall()
        return [(title, body, f"{1-distance:.2f}") for title, body, distance in results if distance <= 0.70]
