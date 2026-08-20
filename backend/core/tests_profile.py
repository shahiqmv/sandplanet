"""Company Profile — ongoing-entry CRUD + reorder + access + images."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import ProfileEntry, ProfileGalleryImage, User
from .tests import make_user


def _img(w, h, name="p.jpg"):
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), "#0E3A5C").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


class ProfileEntryTests(TestCase):
    def setUp(self):
        self.mkt = make_user("mkt", User.Role.MARKETING)
        self.eng = make_user("pf_eng", User.Role.SITE_ENGINEER)
        self.client = APIClient()

    def test_marketing_crud_and_reorder(self):
        self.client.force_authenticate(self.mkt)
        a = self.client.post("/api/v1/profile/entries", {
            "project_name": "Soneva Jani", "client_display": "SONEVA JANI",
            "summary": "Villa works.", "start_value": "April 2026"},
            format="json")
        self.assertEqual(a.status_code, 201, a.data)
        a_id = a.data["id"]
        self.assertEqual(a.data["start_label"], "Commenced")
        b_id = self.client.post("/api/v1/profile/entries",
                                {"project_name": "Vakkaru"},
                                format="json").data["id"]
        d = self.client.get("/api/v1/profile/entries").data
        self.assertEqual(len(d["ongoing"]), 2)
        # reorder b before a
        self.client.post("/api/v1/profile/entries/reorder",
                         {"order": [b_id, a_id]}, format="json")
        d = self.client.get("/api/v1/profile/entries").data
        self.assertEqual(d["ongoing"][0]["id"], b_id)
        # edit
        r = self.client.patch(f"/api/v1/profile/entries/{a_id}",
                              {"summary": "Updated."}, format="json")
        self.assertEqual(r.data["summary"], "Updated.")
        # delete
        self.assertEqual(
            self.client.delete(f"/api/v1/profile/entries/{b_id}").status_code,
            204)
        self.assertEqual(ProfileEntry.objects.count(), 1)

    def test_name_required(self):
        self.client.force_authenticate(self.mkt)
        r = self.client.post("/api/v1/profile/entries", {"summary": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_non_profile_role_forbidden(self):
        self.client.force_authenticate(self.eng)
        self.assertEqual(
            self.client.get("/api/v1/profile/entries").status_code, 403)
        self.assertEqual(self.client.post(
            "/api/v1/profile/entries", {"project_name": "x"},
            format="json").status_code, 403)

    def test_featured_is_recropped_to_square(self):
        self.client.force_authenticate(self.mkt)
        eid = self.client.post("/api/v1/profile/entries",
                               {"project_name": "Jani"}, format="json").data["id"]
        r = self.client.post(f"/api/v1/profile/entries/{eid}/featured",
                             {"file": _img(2000, 1200)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["featured_url"])
        from PIL import Image
        img = Image.open(ProfileEntry.objects.get(pk=eid).featured_image)
        self.assertEqual(img.width, img.height)      # forced 1:1
        self.assertLessEqual(img.width, 1300)

    def test_gallery_add_cap_and_remove(self):
        self.client.force_authenticate(self.mkt)
        eid = self.client.post("/api/v1/profile/entries",
                               {"project_name": "Jani"}, format="json").data["id"]
        for _ in range(6):
            r = self.client.post(f"/api/v1/profile/entries/{eid}/gallery",
                                 {"file": _img(1500, 1000)}, format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["gallery"]), 6)
        # seventh is refused
        r7 = self.client.post(f"/api/v1/profile/entries/{eid}/gallery",
                             {"file": _img(1500, 1000)}, format="multipart")
        self.assertEqual(r7.status_code, 400)
        # a stored gallery image is 3:2
        from PIL import Image
        g = ProfileGalleryImage.objects.filter(entry_id=eid).first()
        im = Image.open(g.image)
        self.assertAlmostEqual(im.width / im.height, 1.5, places=2)
        self.assertEqual(self.client.delete(
            f"/api/v1/profile/gallery/{g.id}").status_code, 204)

    def test_build_html_has_static_pages_and_entries(self):
        from . import profile_render as pr
        ProfileEntry.objects.create(project_name="Vakkaru", status="ONGOING",
                                    sort_order=10)
        html = pr.build_html()
        self.assertIn("Company<br>Profile", html)   # cover title
        self.assertIn("Corporate Information", html)  # static front matter
        self.assertIn("Vakkaru", html)              # the ongoing entry
        self.assertIn("Cheval Blanc", html)         # a referee

    def test_generate_returns_a_pdf(self):
        ProfileEntry.objects.create(project_name="Soneva Jani",
                                    client_display="SONEVA JANI",
                                    summary="Villa works.", status="ONGOING",
                                    sort_order=10)
        self.client.force_authenticate(self.mkt)
        r = self.client.post("/api/v1/profile/generate")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertEqual(r.content[:4], b"%PDF")

    def test_completed_entry_is_locked(self):
        e = ProfileEntry.objects.create(
            project_name="Done", status="COMPLETED", snapshot_locked=True)
        self.client.force_authenticate(self.mkt)
        self.assertEqual(self.client.patch(
            f"/api/v1/profile/entries/{e.id}", {"summary": "x"},
            format="json").status_code, 400)
        self.assertEqual(self.client.delete(
            f"/api/v1/profile/entries/{e.id}").status_code, 400)


class ProfileEditableContentTests(TestCase):
    """Management, corporate info and the cover photo were hardcoded in the
    renderer — a director or a headcount change meant editing code and
    deploying (owner 2026-08-19). These assert the edit reaches the PDF, which
    is the only thing that actually matters.
    """

    def setUp(self):
        self.mkt = make_user("pf_mkt2", User.Role.MARKETING)
        self.eng = make_user("pf_eng2", User.Role.SITE_ENGINEER)
        self.client = APIClient()
        self.client.force_authenticate(self.mkt)

    def test_the_seed_reproduces_the_old_hardcoded_content(self):
        """The PDF must not change the day this lands."""
        from .models import ProfileCorporateRow, ProfileManagement
        self.assertEqual(ProfileManagement.objects.count(), 4)
        self.assertEqual(ProfileCorporateRow.objects.count(), 8)
        names = list(ProfileManagement.objects.values_list("name", flat=True))
        self.assertIn("Ahmed Shahiq", names)
        self.assertIn("Waseem Ali", names)

    def test_a_fifth_person_reaches_the_pdf(self):
        from . import profile_render as pr
        r = self.client.post("/api/v1/profile/management", {
            "name": "Aishath Nasheed", "role": "Director, Finance",
            "intro": "Leads the finance function."}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        html = pr.build_html()
        self.assertIn("Aishath Nasheed", html)
        self.assertIn("Director, Finance", html)

    def test_hiding_a_person_takes_them_off_the_leadership_page(self):
        """Scoped to the Management page on purpose: the same four names are
        ALSO typed into the corporate table's "Senior management" row, so the
        two lists are maintained separately."""
        from . import profile_render as pr
        from .models import ProfileManagement
        p = ProfileManagement.objects.get(name="Waseem Ali")
        self.assertIn("Waseem Ali", pr._management())
        r = self.client.patch(f"/api/v1/profile/management/{p.id}", {
            "name": p.name, "role": p.role, "intro": p.intro,
            "is_active": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Waseem Ali", pr._management())

    def test_the_leadership_page_and_the_corporate_row_are_separate_lists(self):
        """Worth pinning: adding a director means editing BOTH, and nothing in
        the code makes that obvious."""
        from . import profile_render as pr
        self.client.post("/api/v1/profile/management", {
            "name": "Aishath Nasheed", "role": "Director, Finance"},
            format="json")
        self.assertIn("Aishath Nasheed", pr._management())
        self.assertNotIn("Aishath Nasheed", pr._corporate())

    def test_the_headcount_can_be_corrected(self):
        from . import profile_render as pr
        from .models import ProfileCorporateRow
        row = ProfileCorporateRow.objects.get(label="Total staff")
        self.assertIn("106 personnel", pr.build_html())
        r = self.client.patch(f"/api/v1/profile/corporate/{row.id}",
                              {"label": "Total staff",
                               "value": "118 personnel"}, format="json")
        self.assertEqual(r.status_code, 200)
        html = pr.build_html()
        self.assertIn("118 personnel", html)
        self.assertNotIn("106 personnel", html)

    def test_vision_and_mission_are_editable(self):
        from . import profile_render as pr
        r = self.client.patch("/api/v1/profile/settings",
                              {"vision": "A brand new vision statement.",
                               "mission": "A brand new mission statement."},
                              format="json")
        self.assertEqual(r.status_code, 200)
        html = pr.build_html()
        self.assertIn("A brand new vision statement.", html)
        self.assertIn("A brand new mission statement.", html)

    def test_the_cover_photo_is_chosen_not_inherited(self):
        """Without one it falls back to the first ongoing project — which is
        the behaviour that made the cover change on reorder."""
        from . import profile_render as pr
        from .models import ProfileSettings
        entry = self.client.post("/api/v1/profile/entries",
                                 {"project_name": "Vakkaru"},
                                 format="json").data
        self.client.post(f"/api/v1/profile/entries/{entry['id']}/featured",
                         {"file": _img(900, 900)}, format="multipart")
        st = ProfileSettings.get()
        self.assertFalse(bool(st.cover_image))       # falls back today
        r = self.client.post("/api/v1/profile/cover",
                             {"file": _img(1200, 1600, "cover.jpg")},
                             format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["cover_url"])
        st.refresh_from_db()
        self.assertTrue(bool(st.cover_image))
        # and it can be put back
        d = self.client.delete("/api/v1/profile/cover")
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.data["cover_url"], "")

    def test_the_logo_is_vector_so_compression_cannot_pixelate_it(self):
        """The final PDF is Ghostscripted to 110dpi to stay emailable, which
        downsampled the logo with the photographs (owner 2026-08-19)."""
        from . import profile_render as pr
        html = pr.build_html()
        self.assertIn("data:image/svg+xml", html)
        self.assertNotIn("data:image/png", html)

    def test_a_site_role_cannot_edit_any_of_it(self):
        self.client.force_authenticate(self.eng)
        for path in ("/api/v1/profile/management", "/api/v1/profile/corporate",
                     "/api/v1/profile/settings"):
            self.assertEqual(self.client.get(path).status_code, 403, path)


class CoverStyleTests(TestCase):
    """The cover looked like every inside page — photo on top, text block
    below — which is not a cover (owner 2026-08-19). Three treatments now, and
    the crop shape follows the one chosen.
    """

    def setUp(self):
        self.mkt = make_user("cv_mkt", User.Role.MARKETING)
        self.client = APIClient()
        self.client.force_authenticate(self.mkt)

    def test_full_bleed_is_the_default(self):
        from .models import ProfileSettings
        self.assertEqual(ProfileSettings.get().cover_style, "TOP")

    def test_each_style_renders_its_own_layout(self):
        from . import profile_render as pr
        from .models import ProfileSettings
        st = ProfileSettings.get()
        for style, marker in (("TOP", "fc-scrim-top"), ("FULL", "fc-scrim"),
                              ("BAND", "cov-band")):
            st.cover_style = style
            st.save()
            html = pr.build_html()
            self.assertIn(marker, html, style)

    def test_the_crop_shape_follows_the_style(self):
        """Full-bleed needs the whole page; the band needs a wide strip.
        Cropping to the wrong one throws away the sides of the photo."""
        from .profile import cover_aspect
        self.assertEqual(cover_aspect("TOP")[:2], (210, 297))
        self.assertEqual(cover_aspect("FULL")[:2], (210, 297))
        self.assertEqual(cover_aspect("BAND")[:2], (210, 176))

    def test_the_api_reports_the_aspect_for_the_cropper(self):
        r = self.client.get("/api/v1/profile/settings")
        self.assertEqual(r.status_code, 200)
        self.assertAlmostEqual(r.data["cover_aspect"], 210 / 297, places=3)
        r2 = self.client.patch("/api/v1/profile/settings",
                               {"cover_style": "BAND"}, format="json")
        self.assertAlmostEqual(r2.data["cover_aspect"], 210 / 176, places=3)

    def test_a_bad_style_is_ignored_rather_than_stored(self):
        from .models import ProfileSettings
        r = self.client.patch("/api/v1/profile/settings",
                              {"cover_style": "NONSENSE"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ProfileSettings.get().cover_style, "TOP")


class CompleteAndReopenTests(TestCase):
    """Retiring a finished project into the references section.

    The model has carried status / completed_at / snapshot_locked since it was
    built and the renderer reads them, but NOTHING ever set them — there was no
    way to move a project to references at all (owner 2026-08-20).
    """

    def setUp(self):
        self.mkt = make_user("cm_mkt", User.Role.MARKETING)
        self.client = APIClient()
        self.client.force_authenticate(self.mkt)
        self.entry = self.client.post(
            "/api/v1/profile/entries",
            {"project_name": "Kids Pool", "summary": "Design and build."},
            format="json").data

    def _complete(self, when="2026-06-30"):
        return self.client.post(
            f"/api/v1/profile/entries/{self.entry['id']}/complete",
            {"completed_at": when}, format="json")

    def test_completing_moves_it_to_references_and_freezes_it(self):
        r = self._complete()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "COMPLETED")
        self.assertEqual(str(r.data["completed_at"]), "2026-06-30")
        self.assertTrue(r.data["locked"])

    def test_a_frozen_reference_cannot_be_edited(self):
        """The point of freezing: a delivered project must not drift when
        somebody edits copy years later."""
        self._complete()
        r = self.client.patch(f"/api/v1/profile/entries/{self.entry['id']}",
                              {"project_name": "Something else"},
                              format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("locked", r.data["detail"])

    def test_it_can_be_reopened_and_edited_again(self):
        """Because the first thing anyone does after completing something is
        spot a typo in it."""
        self._complete()
        r = self.client.post(
            f"/api/v1/profile/entries/{self.entry['id']}/reopen")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "ONGOING")
        self.assertFalse(r.data["locked"])
        e = self.client.patch(f"/api/v1/profile/entries/{self.entry['id']}",
                              {"project_name": "Kids Pool Phase 2"},
                              format="json")
        self.assertEqual(e.status_code, 200)

    def test_completing_twice_is_refused(self):
        self._complete()
        self.assertEqual(self._complete().status_code, 400)

    def test_an_invalid_date_is_refused(self):
        r = self._complete("not-a-date")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Invalid", r.data["detail"])

    def test_no_date_given_means_today(self):
        from datetime import date
        r = self.client.post(
            f"/api/v1/profile/entries/{self.entry['id']}/complete",
            {}, format="json")
        self.assertEqual(str(r.data["completed_at"]), str(date.today()))

    def test_it_appears_under_references_in_the_pdf(self):
        from . import profile_render as pr
        self._complete()
        html = pr.build_html()
        self.assertIn("PROJECT<br>REFERENCES", html)


class ProfileLegibilityTests(TestCase):
    """Two things that were simply unreadable or invisible on the page."""

    def test_the_mission_text_is_light_on_the_navy_panel(self):
        """.vmbox p and .amberbox p have EQUAL specificity, so whichever is
        declared later wins. With the order reversed the dark body colour
        landed on the navy panel and the mission could not be read (owner
        2026-08-20)."""
        from . import profile_render as pr
        css = pr._CSS_TEXT
        self.assertLess(css.index(".vmbox p{"), css.index(".amberbox p{"))
        amber = css[css.index(".amberbox p{"):]
        self.assertIn("#F2ECE0", amber[:60])

    def test_the_divider_shows_a_meaningful_slice_of_the_photo(self):
        """74mm of a 210mm page is a quarter of the picture — on the pool
        aerial that was water and nothing else."""
        from . import profile_render as pr
        css = pr._CSS_TEXT
        i = css.index(".div-strip{")
        self.assertIn("width:92mm", css[i:i + 120])
