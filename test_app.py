from contextlib import closing
from datetime import date, timedelta
from functools import partial
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, build_opener

from app import Portal, connect, initialize
from community import CommunityStores


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.database = Path(scratch.name) / "test.sqlite3"
        initialize(self.database)
        stores = CommunityStores(self.database).__enter__()
        self.addCleanup(stores.close)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Portal, database=self.database, stores=stores))
        self.addCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}"
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, path, data=None, status=200):
        payload = urlencode(data).encode() if data is not None else None
        try:
            response = self.client.open(self.url + path, payload, timeout=8)
        except HTTPError as ex:
            response = ex
        with response:
            content = response.read().decode()
            self.assertEqual(response.code, status, content[:500])
            return content

    def token(self, path):
        return re.search(r'name="token" value="([^"]+)"', self.request(path))[1]

    def post(self, path, action, expected_status=200, **data):
        token = self.token(path)
        return self.request(path, dict(data, token=token, action=action), expected_status)

    def login(self, role):
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        page = self.post("/login", "login", username=role, password=role.title()+"Demo123")
        self.assertIn("Overview", page)

    def test_billing_trigger_ledger_and_resident_scope(self):
        self.login("admin")
        self.assertIn("₹2,500.00", self.post("/billing","payment",bill=1,amount=1000,reference="PART-001"))
        rejected = self.post("/billing","payment",422,bill=1,amount="2500.01",reference="TOO-MUCH")
        self.assertIn("Payment exceeds outstanding balance", rejected)
        month = date.today().strftime("%Y-%m")
        self.post("/billing","bill",422,unit=1,period=month,amount=500,due=date.today())
        self.post("/billing","bill",unit=2,period=month,amount=500,due=date.today())
        self.login("resident")
        page = self.request("/billing")
        self.assertIn("₹2,500.00", page)
        self.assertNotIn("A-102", page)
        self.request("/billing", {"token":self.token("/billing"), "action":"payment"}, 403)
        self.request("/units", status=404)

    def test_occupancy_registration_is_atomic(self):
        self.login("admin")
        self.post("/units","unit",block="C",number="304",bedrooms=2)
        resident = dict(kind="Tenant", name="Demo Tenant", username="new.tenant", password="Temporary123")
        self.post("/units","register",422,unit=999,**resident)
        self.assertIn("Demo Tenant", self.post("/units","register",unit=5,**resident))
        self.post("/units","moveout",occupancy=2)
        self.post("/units","movein",unit=3,kind="Tenant",user=4)
        self.post("/units","movein",422,unit=4,kind="Tenant",user=4)
        with closing(connect(self.database)) as db:
            records = db.execute("SELECT unit_id,end_date FROM occupancies WHERE user_id=4 ORDER BY id").fetchall()
            self.assertEqual([tuple(row) for row in records], [(5,date.today().isoformat()),(3,None)])

    def test_requests_bookings_and_cross_role_updates(self):
        self.login("resident")
        self.post("/tickets","ticket",subject="Lift panel",description="Display is blank")
        self.request("/tickets", {"token":"invalid", "action":"ticket"}, 403)
        tomorrow = date.today() + timedelta(days=1)
        slot = dict(facility=1,day=tomorrow,hour=10)
        self.post("/bookings","booking",**slot)
        self.post("/bookings","booking",422,**slot)
        self.post("/bookings","cancel",booking=1)
        self.post("/bookings","booking",**slot)
        self.login("admin")
        self.post("/tickets","status",ticket=2,status="In progress")
        self.post("/notices","notice",title="Water test",body="Inspection on Friday")
        self.post("/parking","slot",slot="P-04")
        self.post("/parking","assign",slot=4,unit=1,vehicle="TEST-1")
        self.post("/parking","assign",422,slot=4,unit=2,vehicle="TEST-2")
        self.login("resident")
        self.assertIn("In progress", self.request("/tickets"))
        self.assertIn("Water test", self.request("/notices"))
        self.assertIn("TEST-1", self.request("/parking"))
        self.login("admin")
        self.post("/parking","release",slot=4)
        self.assertNotIn("TEST-1", self.request("/parking"))

    def test_complaint_workflow_and_privacy(self):
        self.login("admin")
        self.post("/units","register",unit=1,kind="Tenant",name="Second Resident",
                  username="second",password="SecondDemo123")
        self.login("resident")
        self.post("/complaints","complaint",422,category="Invalid",subject="Noise",description="Loud music")
        page = self.post("/complaints","complaint",category="Noise",subject="Late music",description="Loud music")
        self.assertIn("Late music",page)
        self.assertIn("Open",page)
        self.post("/complaints","complaint_response",403,complaint=1,status="Resolved",response="Forbidden")
        self.login("admin")
        self.post("/complaints","complaint_response",complaint=1,status="In progress",response="We will investigate.")
        self.login("resident")
        page = self.request("/complaints")
        self.assertIn("In progress",page)
        self.assertIn("We will investigate.",page)
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        self.post("/login","login",username="second",password="SecondDemo123")
        self.assertNotIn("Late music",self.request("/complaints"))
        self.login("guard")
        self.request("/complaints",status=404)

    def test_gate_check_in_and_checkout(self):
        self.login("guard")
        self.request("/billing",status=404)
        self.assertIn("Demo Visitor", self.post("/visits","arrival",unit=1,visitor="Demo Visitor",purpose="Delivery"))
        self.post("/visits","departure",visit=1)
        self.post("/visits","departure",422,visit=1)
        with closing(connect(self.database)) as db:
            self.assertIsNotNone(db.execute("SELECT departed_at FROM visits WHERE id=1").fetchone()[0])

    def test_directory_and_vector_search(self):
        self.login("admin")
        contact = dict(name="Club desk",category="Facilities",channel="Visit Hall A",hours="Saturday")
        self.assertIn("Visit Hall A",self.post("/directory","directory_add",**contact))
        self.post("/directory","directory_add",422,**contact)
        self.post("/directory","directory_remove",422,contact=9999)
        self.login("resident")
        self.assertIn("Club desk",self.request("/directory"))
        self.post("/directory","directory_remove",403,contact=3)
        page = self.request("/help?q=neighbors+are+too+loud")
        self.assertIn("File a community complaint",page)
        self.assertNotIn("Check your maintenance bill",page)
        self.assertIn("No matching help articles",self.request("/help?q=astronomy"))
        self.login("admin")
        self.assertNotIn("Club desk",self.post("/directory","directory_remove",contact=3))

    def test_directory_persists_on_reopen(self):
        source = self.database.with_name("reopen.sqlite3")
        with CommunityStores(source) as stores:
            stores.add_contact("Club desk","Facilities","Visit Hall A","")
        with CommunityStores(source) as stores:
            entry = next(row for row in stores.directory() if row["name"] == "Club desk")
            self.assertEqual(entry["contact"],{"channel":"Visit Hall A"})
            self.assertEqual(stores.search_help("broken")[0][0],"Request a repair")


if __name__ == "__main__":
    unittest.main()
