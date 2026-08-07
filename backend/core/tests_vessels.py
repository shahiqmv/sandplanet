"""FollowMe local-vessel tracking — adapter parsing + proxy endpoints.

The provider wraps its JSON in an HTML page and puts no coordinates in the
list (only a reverse-geocoded `port`); the detail call adds lat/lon/course.
These tests pin both shapes so a provider quirk can't silently break the
Loading-Manifest picker or the live map pin.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import followme
from .models import User
from .tests import make_user

# Real list shape: {"<id>": {name,speed,time,type,image,port}} — no coords.
LIST_RAW = (
    '<html><body>{"status":"ok","data":{'
    '"17097":{"name":"MTCC Kalhihi","speed":"22.0",'
    '"time":"2026-08-07 09:10:33","type":"Speed Boat",'
    '"image":"x.png","port":"K. Thilafushi"},'
    '"10696":{"name":"MUSAAFIRU","speed":"7.0",'
    '"time":"2026-08-07 08:00:00","type":"Supply Boat",'
    '"image":"y.png","port":"AA. Rasdhoo"},'
    '"20500":{"name":"ASURUMAA","speed":"0.0",'
    '"time":"2026-08-07 07:30:00","type":"Landing Craft",'
    '"image":"z.png","port":"Male Commercial Harbour"}'
    '}}</body></html>'
)

# Detail shape: adds course/lat/lon for the map pin.
DETAIL_RAW = (
    '<html><body>{"status":"ok","data":{"17097":{'
    '"name":"MTCC Kalhihi","speed":"22.0","course":"148",'
    '"lat":"4.8691950","lon":"73.1871600",'
    '"time":"2026-08-07 09:10:33","type":"Speed Boat"}}}</body></html>'
)


@override_settings(FOLLOWME_API_KEY="test-key",
                   FOLLOWME_BASE_URL="https://followme.mv/api/v5")
class FollowMeAdapterTests(TestCase):
    def setUp(self):
        followme._cache.update(at=0.0, vessels=None)   # never serve a stale list

    def test_atoll_of(self):
        self.assertEqual(followme.atoll_of("K. Thilafushi"), "K")
        self.assertEqual(followme.atoll_of("AA. Rasdhoo"), "AA")
        self.assertEqual(followme.atoll_of("Male Commercial Harbour"), "")
        self.assertEqual(followme.atoll_of(""), "")
        self.assertEqual(followme.atoll_of(None), "")

    def test_list_parses_html_wrapped_json(self):
        with patch.object(followme, "_http_get", return_value=LIST_RAW):
            vessels = followme.list_vessels()
        self.assertEqual(len(vessels), 3)
        names = [v["name"] for v in vessels]
        self.assertEqual(names, sorted(names, key=str.lower))   # name-sorted
        kalhihi = next(v for v in vessels if v["id"] == "17097")
        self.assertEqual(kalhihi["atoll"], "K")
        self.assertEqual(kalhihi["speed"], 22.0)
        self.assertIsNone(kalhihi["lat"])          # list carries no position

    def test_list_is_cached(self):
        with patch.object(followme, "_http_get", return_value=LIST_RAW) as m:
            followme.list_vessels()
            followme.list_vessels()
        self.assertEqual(m.call_count, 1)          # second call served from cache

    def test_detail_extracts_coordinates(self):
        with patch.object(followme, "_http_get", return_value=DETAIL_RAW):
            v = followme.vessel("17097")
        self.assertEqual(v["name"], "MTCC Kalhihi")
        self.assertEqual(v["lat"], 4.869195)
        self.assertEqual(v["lon"], 73.18716)
        self.assertEqual(v["course"], 148.0)

    def test_missing_key_raises(self):
        with override_settings(FOLLOWME_API_KEY=""):
            with self.assertRaises(followme.FollowMeError):
                followme._http_get("")


@override_settings(FOLLOWME_API_KEY="test-key")
class VesselEndpointTests(TestCase):
    def setUp(self):
        followme._cache.update(at=0.0, vessels=None)
        self.client = APIClient()
        self.client.force_authenticate(make_user("u1", User.Role.HO_PURCHASING))

    def test_requires_auth(self):
        anon = APIClient()
        self.assertEqual(anon.get("/api/v1/vessels").status_code, 403)

    def test_list_filters_and_facets(self):
        with patch.object(followme, "_http_get", return_value=LIST_RAW):
            r = self.client.get("/api/v1/vessels")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total"], 3)
        self.assertIn("AA", r.data["atolls"])
        self.assertIn("K", r.data["atolls"])

        with patch.object(followme, "_http_get", return_value=LIST_RAW):
            r = self.client.get("/api/v1/vessels", {"atoll": "AA"})
        self.assertEqual(r.data["total"], 1)
        self.assertEqual(r.data["vessels"][0]["name"], "MUSAAFIRU")

        with patch.object(followme, "_http_get", return_value=LIST_RAW):
            r = self.client.get("/api/v1/vessels", {"q": "kalh"})
        self.assertEqual(r.data["total"], 1)

        with patch.object(followme, "_http_get", return_value=LIST_RAW):
            r = self.client.get("/api/v1/vessels", {"supply": "1"})
        got = {v["name"] for v in r.data["vessels"]}
        self.assertEqual(got, {"MUSAAFIRU", "ASURUMAA"})   # supply + landing craft

    def test_detail_returns_position(self):
        with patch.object(followme, "_http_get", return_value=DETAIL_RAW):
            r = self.client.get("/api/v1/vessels/17097")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["lat"], 4.869195)
        self.assertEqual(r.data["course"], 148.0)

    def test_provider_down_returns_503(self):
        def boom(_):
            raise followme.FollowMeError("FollowMe 500")
        with patch.object(followme, "_http_get", side_effect=boom):
            r = self.client.get("/api/v1/vessels")
        self.assertEqual(r.status_code, 503)
