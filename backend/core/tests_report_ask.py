"""Ask Claude about a report (owner 2026-11-09): the reader's rights live in
the tools, every question is a record, follow-ups carry the thread."""
import json
import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from . import report_ask
from .models import (Attendance, AuditLog, Employee, ManpowerCategory,
                     PayrollLine, PayrollRun, ReportAnalysis, Site,
                     SitePmHistory, User)
from .tests import make_user

D = Decimal

ANSWER = {"title": "Overtime, three months", "summary": "OT fell.",
          "sections": [{"heading": "By month", "paragraphs": ["Down 10%."],
                        "bullets": [], "table": {
                            "columns": [{"label": "Month", "kind": "text"},
                                        {"label": "Hours", "kind": "num"}],
                            "rows": [["Oct 2026", 13]]}}],
          "caveats": ["September is not locked."]}


def _usage(i=1000, o=200):
    return SimpleNamespace(input_tokens=i, output_tokens=o,
                           cache_creation_input_tokens=0,
                           cache_read_input_tokens=0)


def text_turn(obj=ANSWER, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, model="claude-opus-5-5",
                           usage=_usage(),
                           content=[SimpleNamespace(type="text",
                                                    text=json.dumps(obj))])


def tool_turn(*calls):
    blocks = [SimpleNamespace(type="tool_use", id=f"tu_{i}", name=n, input=a)
              for i, (n, a) in enumerate(calls)]
    return SimpleNamespace(stop_reason="tool_use", model="claude-opus-5-5",
                           usage=_usage(), content=blocks)


class Model:
    """Stands in for Claude: hands out scripted turns and keeps what it was
    sent, so a test can read the tool results the loop produced."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def __call__(self, client, model, system, messages):
        self.seen.append([dict(m) for m in messages])
        return self.turns.pop(0)

    def results(self):
        """Every tool_result block the loop sent back, in order."""
        out = []
        for m in self.seen[-1]:
            if m["role"] == "user" and isinstance(m["content"], list):
                out += [b for b in m["content"]
                        if b.get("type") == "tool_result"]
        return out


class AskCase(TestCase):
    def setUp(self):
        self.sjr = Site.objects.create(code="SJR", name="Soneva Jani",
                                       status=Site.Status.ACTIVE)
        self.vkr = Site.objects.create(code="VKR", name="Vakkaru",
                                       status=Site.Status.ACTIVE)
        self.director = make_user("ask_pd", User.Role.DIRECTOR)
        self.director.excom = True
        self.director.save(update_fields=["excom"])
        self.qs = make_user("ask_qs", User.Role.QS)
        self.qs.excom = True
        self.qs.save(update_fields=["excom"])
        self.fin = make_user("ask_fin", User.Role.FINANCE)
        self.pm = make_user("ask_pm", User.Role.PM)
        SitePmHistory.objects.create(site=self.sjr, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        mason = ManpowerCategory.objects.create(name="Mason", grp="WORKER",
                                                sort_order=1)
        self.w1 = Employee.objects.create(emp_no="EMP-9101", full_name="Mason A",
                                          basic_pay=6000, job_category=mason)
        self.w2 = Employee.objects.create(emp_no="EMP-9102", full_name="Mason B",
                                          basic_pay=6000, job_category=mason)
        for d in (1, 2, 3):
            Attendance.objects.create(employee=self.w1, site=self.sjr,
                                      day=date(2026, 10, d), remark="PRESENT",
                                      ot_requested=3, ot_approved=3)
        Attendance.objects.create(employee=self.w2, site=self.sjr,
                                  day=date(2026, 10, 1), remark="PRESENT",
                                  ot_requested=2, ot_approved=2)
        Attendance.objects.create(employee=self.w2, site=self.vkr,
                                  day=date(2026, 10, 2), remark="PRESENT",
                                  ot_requested=5, ot_approved=5)
        self.run = PayrollRun.objects.create(
            ref="PAY-SJR-2026-10", site=self.sjr, kind="MONTHLY",
            currency="MVR", year=2026, month=10, working_days=26,
            status="LOCKED", created_by=self.fin)
        PayrollLine.objects.create(run=self.run, employee=self.w1,
                                   site=self.sjr, basic_pay=6000, ot_rate=30,
                                   days_worked=26, ot_hours=9)
        self.c = APIClient()
        self.env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "t"})
        self.env.start()
        self.client_patch = mock.patch.object(report_ask, "_client",
                                              lambda: None)
        self.client_patch.start()

    def tearDown(self):
        self.env.stop()
        self.client_patch.stop()

    def ask(self, user, question, site=None, report="manpower", **extra):
        self.c.force_authenticate(user)
        body = {"report": report, "site": site or self.sjr.id,
                "from": "2026-10-01", "to": "2026-10-31",
                "question": question, **extra}
        return self.c.post("/api/v1/reports/ask", body, format="json")


class AccessTests(AskCase):
    def test_only_readers_may_ask(self):
        with mock.patch.object(report_ask, "_request", Model([text_turn()])):
            self.assertEqual(self.ask(self.fin, "Why?").status_code, 403)
            self.assertEqual(
                self.ask(self.pm, "Why?", site="all").status_code, 403)
            self.assertEqual(
                self.ask(self.pm, "Why?", site=self.vkr.id).status_code, 400)

    def test_a_question_is_a_record_with_its_steps_and_cost(self):
        model = Model([tool_turn(("overtime_by_person",
                                  {"scope": "SJR", "from": "2026-08-01",
                                   "to": "2026-10-31", "limit": 10})),
                       text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            r = self.ask(self.pm, "Who earned the most overtime?")
        self.assertEqual(r.status_code, 202, r.data)
        a = r.data["analysis"]
        self.assertEqual(a["status"], "DONE")
        self.assertEqual(a["answer"]["title"], "Overtime, three months")
        self.assertEqual(a["steps"], ["Looked at overtime person by person "
                                      "for SJR, 2026-08-01 to 2026-10-31"])
        self.assertEqual(a["input_tokens"], 2000)
        self.assertEqual(D(a["cost_usd"]), D("0.016"))   # 2000×4 + 400×20
        # the opening turn carried the report on screen and the question
        first = model.seen[0][0]["content"]
        self.assertIn("The report on screen", first[0]["text"])
        self.assertEqual(first[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(first[1]["text"], "Who earned the most overtime?")
        self.assertTrue(AuditLog.objects.filter(
            event="REPORT_ASKED", detail__report="manpower").exists())
        # the record is the asker's alone
        self.c.force_authenticate(self.director)
        self.assertEqual(self.c.get(f"/api/v1/reports/ask/{a['id']}")
                         .status_code, 404)
        self.c.force_authenticate(self.pm)
        self.assertEqual(self.c.get(f"/api/v1/reports/ask/{a['id']}")
                         .data["analysis"]["id"], a["id"])


class ToolRightsTests(AskCase):
    def test_a_pm_gets_hours_but_never_pay(self):
        model = Model([tool_turn(("overtime_by_person",
                                  {"scope": "SJR", "from": "2026-10-01",
                                   "to": "2026-10-31", "limit": 10})),
                       text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            self.ask(self.pm, "Top overtime?")
        got = json.loads(model.results()[0]["content"])
        self.assertEqual([p["emp_no"] for p in got["people"]],
                         ["EMP-9101", "EMP-9102"])
        self.assertEqual(got["people"][0]["ot_hours"], 9.0)
        self.assertEqual(got["people"][0]["days_with_ot"], 3)
        # B's VKR overtime is not SJR's business
        self.assertEqual(got["people"][1]["ot_hours"], 2.0)
        self.assertNotIn("ot_pay_usd", got["people"][0])
        self.assertIn("not shown to this reader", got["note"])

    def test_a_pm_is_refused_other_sites_the_company_and_individual_pay(self):
        model = Model([tool_turn(("run_report", {"key": "manpower",
                                                 "scope": "all",
                                                 "from": "2026-10-01",
                                                 "to": "2026-10-31"}),
                                 ("run_report", {"key": "manpower",
                                                 "scope": "VKR",
                                                 "from": "2026-10-01",
                                                 "to": "2026-10-31"}),
                                 ("payroll_by_person", {"scope": "SJR",
                                                        "from": "2026-10-01",
                                                        "to": "2026-10-31",
                                                        "limit": 5})),
                       text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            r = self.ask(self.pm, "Compare the sites' pay")
        self.assertEqual(r.data["analysis"]["status"], "DONE")
        res = model.results()
        self.assertEqual(len(res), 3)
        self.assertTrue(all(x.get("is_error") for x in res))
        self.assertIn("company-wide", res[0]["content"])
        self.assertIn("not a site this reader may report on", res[1]["content"])
        self.assertIn("may not see individual pay", res[2]["content"])
        self.assertTrue(all("—" in s for s in r.data["analysis"]["steps"]))

    def test_excom_with_pay_rights_sees_pay_person_by_person(self):
        model = Model([tool_turn(("overtime_by_person",
                                  {"scope": "all", "from": "2026-10-01",
                                   "to": "2026-10-31", "limit": 10}),
                                 ("payroll_by_person",
                                  {"scope": "all", "from": "2026-10-01",
                                   "to": "2026-10-31", "limit": 10})),
                       text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            self.ask(self.director, "Highest OT earners?", site="all")
        ot, pay = (json.loads(x["content"]) for x in model.results())
        a = ot["people"][0]
        self.assertEqual(a["emp_no"], "EMP-9101")
        # 9 h × MVR 30 = MVR 270 → USD at the company rate, from the locked run
        self.assertEqual(a["ot_pay_usd"], round(270 / 15.42, 2))
        self.assertEqual(a["months"]["2026-10"]["ot_pay_usd"], a["ot_pay_usd"])
        self.assertNotIn("ot_pay_usd", ot["people"][1])   # VKR: no locked run
        self.assertEqual(pay["locked_months"], ["2026-10"])
        self.assertEqual(pay["people"][0]["emp_no"], "EMP-9101")
        self.assertIn("gross_usd", pay["people"][0])

    def test_excom_without_pay_rights_is_refused_individual_pay(self):
        model = Model([tool_turn(("payroll_by_person",
                                  {"scope": "all", "from": "2026-10-01",
                                   "to": "2026-10-31", "limit": 10})),
                       text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            self.ask(self.qs, "Pay by person", site="all")
        self.assertTrue(model.results()[0].get("is_error"))

    def test_run_report_hands_over_any_report_the_reader_may_run(self):
        model = Model([tool_turn(("run_report", {"key": "manpower",
                                                 "scope": "SJR",
                                                 "from": "2026-09-01",
                                                 "to": "2026-09-30"})),
                       text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            self.ask(self.pm, "And September?")
        got = json.loads(model.results()[0]["content"])
        self.assertEqual(got["report"], "Manpower cost analysis")
        self.assertEqual(got["scope"], "SJR — Soneva Jani")
        self.assertTrue(got["sections"])


class ThreadTests(AskCase):
    def test_a_follow_up_continues_the_transcript(self):
        with mock.patch.object(report_ask, "_request", Model([text_turn()])):
            first = self.ask(self.pm, "Top overtime?").data["analysis"]
        model = Model([text_turn()])
        with mock.patch.object(report_ask, "_request", model):
            r = self.ask(self.pm, "And in August?", follow_up_of=first["id"])
        self.assertEqual(r.status_code, 202, r.data)
        second = r.data["analysis"]
        self.assertEqual(second["thread"], first["id"])
        sent = model.seen[0]
        self.assertEqual(sent[0]["role"], "user")             # the opening
        self.assertEqual(sent[1]["role"], "assistant")        # first answer
        self.assertEqual(sent[2], {"role": "user", "content": "And in August?"})
        # nobody else can follow up on it
        with mock.patch.object(report_ask, "_request", Model([text_turn()])):
            r = self.ask(self.director, "Mine too", follow_up_of=first["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("not yours", r.data["detail"])
        # the list for the page has both, oldest first
        self.c.force_authenticate(self.pm)
        got = self.c.get("/api/v1/reports/asks", {"report": "manpower",
                                                   "scope": "SJR"}).data
        self.assertEqual([x["id"] for x in got["analyses"]],
                         [first["id"], second["id"]])

    def test_the_thread_prints_on_the_letterhead(self):
        with mock.patch.object(report_ask, "_request", Model([text_turn()])):
            a = self.ask(self.pm, "Top overtime?").data["analysis"]
        self.c.force_authenticate(self.pm)
        r = self.c.get(f"/api/v1/reports/ask/{a['id']}", {"export": "pdf"})
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r["Content-Type"], "application/pdf")


class FailureTests(AskCase):
    def test_a_refusal_and_an_endless_loop_fail_out_loud(self):
        with mock.patch.object(report_ask, "_request",
                               Model([text_turn({}, stop="refusal")])):
            a = self.ask(self.pm, "x").data["analysis"]
        self.assertEqual(a["status"], "FAILED")
        self.assertIn("declined", a["error"])
        turns = [tool_turn(("run_report", {"key": "manpower", "scope": "SJR",
                                           "from": "2026-10-01",
                                           "to": "2026-10-31"}))
                 for _ in range(report_ask._MAX_STEPS + 1)]
        with mock.patch.object(report_ask, "_request", Model(turns)):
            a = self.ask(self.pm, "y").data["analysis"]
        self.assertEqual(a["status"], "FAILED")
        self.assertIn("needed more data", a["error"])
        self.assertEqual(ReportAnalysis.objects.filter(
            status="RUNNING").count(), 0)

    def test_an_unreadable_answer_fails(self):
        bad = SimpleNamespace(stop_reason="end_turn", model="m",
                              usage=_usage(),
                              content=[SimpleNamespace(type="text",
                                                       text="not json")])
        with mock.patch.object(report_ask, "_request", Model([bad])):
            a = self.ask(self.pm, "z").data["analysis"]
        self.assertEqual(a["status"], "FAILED")
        self.assertIn("no readable answer", a["error"])
