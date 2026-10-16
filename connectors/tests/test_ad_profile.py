"""What advertisers and the services keep about you, from the exports: a record for each advertiser that has you
on a list (and how it got you there), each thing a service decided about you, each company that told a service
what you did elsewhere, and each ad you were shown. Exports are made up here, laid out as Meta, X and LinkedIn lay
them out; the importer runs as the app runs it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


def zip_to(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, (str, bytes)) else json.dumps(data))


def lv(label, values):
    return {"label": label, "vec": [{"value": v} for v in values]}


class AdProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t = tempfile.TemporaryDirectory()
        cls.addClassCleanup(t.cleanup)
        corpus = Path(t.name) / "corpus"
        (corpus / "imports").mkdir(parents=True)
        (corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": ["ada_l"]}))
        fb = "ads_information/"
        zip_to(corpus / "imports/facebook/facebook-ada-2026.zip", {
            f"{fb}advertisers_using_your_activity_or_information.json": {"media": [], "label_values": [
                lv("A list uploaded or used by the advertiser", ["Acme Outdoor", "Corner Bakery"]),
                lv("Interactions you may have had with the advertiser's website, app or store", ["Acme Outdoor", "Night Owl Games"])]},
            f"{fb}other_categories_used_to_reach_you.json": {"label_values": [lv("Name", ["Frequent travelers", "Lives away from family"])]},
            "apps_and_websites_off_of_facebook/your_activity_off_meta_technologies.json": [
                {"title": "Night Owl Games", "label_values": [{"label": "ID", "value": "42"}, {"label": "Events", "vec": [
                    {"dict": [{"label": "ID", "value": "1"}, {"label": "Event", "value": "PURCHASE"}, {"label": "Received on", "timestamp_value": 1767225600}]},
                    {"dict": [{"label": "ID", "value": "2"}, {"label": "Event", "value": "PAGE_VIEW"}, {"label": "Received on", "timestamp_value": 1767312000}]},
                    {"dict": [{"label": "ID", "value": "3"}, {"label": "Event", "value": "PAGE_VIEW"}, {"label": "Received on", "timestamp_value": 1767398400}]}]}]}],
            "apps_and_websites_off_of_facebook/your_activity_off_meta_technologies_settings.json": {"label_values": [{"label": "Setting", "value": "On"}]},
            "your_facebook_activity/ai/interest_categories.json": [{"timestamp": 1767225600, "label_values": [{"label": "Interest", "value": "Rock climbing"}]}],
        })
        zip_to(corpus / "imports/instagram/instagram-ada-2026.zip", {
            "ads_information/instagram_ads_and_businesses/advertisers_using_your_activity_or_information.json": {"label_values": [
                lv("Advertisers that have uploaded an audience list containing entries that were matched to your Instagram profile", ["Corner Bakery"]),
                lv("Advertisers whose store you visited", ["Corner Bakery"])]},
            "ads_information/ads_and_topics/ads_viewed.json": [{"timestamp": 1767225600, "label_values": [
                {"label": "URL", "value": "https://www.instagram.com/p/abc"}, {"label": "Caption", "value": "New trail shoes are here"},
                {"title": "Owner", "dict": [{"title": "Acme Outdoor", "dict": [{"label": "URL", "value": "https://www.instagram.com/acme"}]}]}]}],
        })
        personalization = [{"p13nData": {"demographics": {"languages": [{"language": "English", "isDisabled": False}], "genderInfo": {"gender": "female"}},
                                         "interests": {"interests": [{"name": "Bouldering", "isDisabled": False}, {"name": "Golf", "isDisabled": True}],
                                                       "partnerInterests": [], "audienceAndAdvertisers": {"lookalikeAdvertisers": ["@lookalike"], "advertisers": ["@acme", "@bakery"],
                                                                                                         "doNotReachAdvertisers": [], "catalogAudienceAdvertisers": [], "numAudiences": "12"},
                                                       "shows": ["The Great British Bake Off"]},
                                         "locationHistory": ["Chicago, IL"], "inferredAgeInfo": {"age": ["25-34"], "birthDate": ""}}}]
        conversions = [{"ad": {"adsUserData": {"attributedOnlineConversions": {"conversions": [
            {"attributedConversionType": "SiteVisit", "eventType": "{}", "conversionPlatform": "Mobile", "conversionUrl": "https://acme.example/shoes",
             "advertiserInfo": {"advertiserName": "Acme Outdoor", "screenName": "@acme"}, "conversionTime": "2026-01-02 10:00:00", "additionalParameters": {}}]}}}}]
        impressions = [{"ad": {"adsUserData": {"adImpressions": {"impressions": [
            {"displayLocation": "TimelineHome", "advertiserInfo": {"advertiserName": "Corner Bakery", "screenName": "@bakery"},
             "matchedTargetingCriteria": [{"targetingType": "Locations", "targetingValue": "Chicago"}, {"targetingType": "Age", "targetingValue": "25 to 34"}],
             "impressionTime": "2026-01-03 09:00:00"}]}}}}]
        zip_to(corpus / "imports/x/twitter-2026.zip", {
            "data/account.js": "window.YTD.account.part0 = " + json.dumps([{"account": {"accountId": "1"}}]),
            "data/personalization.js": "window.YTD.personalization.part0 = " + json.dumps(personalization),
            "data/ad-online-conversions-attributed.js": "window.YTD.ad_online_conversions_attributed.part0 = " + json.dumps(conversions),
            "data/ad-impressions.js": "window.YTD.ad_impressions.part0 = " + json.dumps(impressions),
        })
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Member Age", "Member Interests", "Company Names", "Company Names", "Member Traits"])
        w.writerow(["25 to 34", "Climbing;Baking; ;N/A", "Acme;Corner Bakery", "Acme", "Frequent traveler"])
        inf = io.StringIO()
        w = csv.writer(inf)
        w.writerow(["Category", "Type of inference", "Description", "Inference"])
        w.writerow(["Inferred interests", "Affinity for Electric Vehicles", "Based on your activity", "Yes"])
        w.writerow(["Inferred personal characteristics", "Inferred gender", "Based on your profile", "Female"])
        zip_to(corpus / "imports/linkedin/Complete_LinkedInDataExport.zip", {"Ad_Targeting.csv": "﻿" + out.getvalue(), "Inferences_about_you.csv": inf.getvalue()})
        r = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], env={**os.environ, "CORPUS_DIR": str(corpus)}, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.recs = {}
        for f in (corpus / "normalized").glob("*.jsonl"):
            cls.recs[f.stem] = [json.loads(line) for line in f.read_text().splitlines()]

    def of(self, source, kind):
        return [r for r in self.recs.get(source, []) if r["kind"] == kind]

    def test_each_advertiser_with_how_it_got_you(self):
        fb = {(r["title"], r["meta"]["how"]) for r in self.of("facebook_activity", "advertiser")}
        self.assertEqual(fb, {("Acme Outdoor", "list"), ("Corner Bakery", "list"), ("Acme Outdoor", "activity"), ("Night Owl Games", "activity")})
        ig = {(r["title"], r["meta"]["how"]) for r in self.of("instagram_activity", "advertiser")}
        self.assertEqual(ig, {("Corner Bakery", "list"), ("Corner Bakery", "store")})
        r = next(r for r in self.of("facebook_activity", "advertiser") if r["meta"]["how"] == "list" and r["title"] == "Acme Outdoor")
        self.assertEqual(r["meta"]["service"], "Facebook")
        self.assertIn("uploaded a list", r["text"])
        x = {(r["title"], r["meta"]["how"]) for r in self.of("x", "advertiser")}
        self.assertEqual(x, {("@acme", "list"), ("@bakery", "list"), ("@lookalike", "lookalike")})

    def test_what_they_decided_about_you(self):
        cats = {r["title"] for r in self.of("facebook_activity", "inference") if r["meta"]["what"] == "category"}
        self.assertEqual(cats, {"Frequent travelers", "Lives away from family"})
        self.assertIn("Rock climbing", {r["title"] for r in self.of("facebook_activity", "inference") if r["meta"]["what"] == "interest"})
        x = {(r["meta"]["what"], r["title"]) for r in self.of("x", "inference")}
        self.assertTrue({("gender", "female"), ("age", "25-34"), ("interest", "Bouldering"), ("interest", "Golf"), ("show", "The Great British Bake Off"),
                         ("location", "Chicago, IL"), ("audiences", "12 audiences"), ("language", "English")} <= x)
        golf = next(r for r in self.of("x", "inference") if r["title"] == "Golf")
        self.assertTrue(golf["meta"]["turned_off"], "an interest you turned off says so")
        li = {(r["meta"]["what"], r["title"]) for r in self.of("linkedin", "inference")}
        self.assertTrue({("Member Interests", "Climbing"), ("Member Interests", "Baking"), ("Company Names", "Acme"), ("Company Names", "Corner Bakery"),
                         ("Member Traits", "Frequent traveler"), ("Member Age", "25 to 34"), ("Inferred interests", "Affinity for Electric Vehicles"),
                         ("Inferred personal characteristics", "Inferred gender: Female")} <= li)
        self.assertFalse(any(r["title"] in ("", "N/A") for r in self.of("linkedin", "inference")))
        self.assertEqual(len([r for r in self.of("linkedin", "inference") if r["title"] == "Acme"]), 1, "a value repeated in two columns of the same name is one record")

    def test_who_told_them_what_you_did_elsewhere(self):
        (r,) = self.of("facebook_activity", "off_platform")
        self.assertEqual(r["title"], "Night Owl Games")
        self.assertEqual([e["type"] for e in r["meta"]["events"]], ["PURCHASE", "PAGE_VIEW", "PAGE_VIEW"])
        self.assertTrue(r["ts"].startswith("2026-01-03"), "dated by the latest")
        self.assertIn("3 times (page view ×2, purchase ×1)", r["text"])
        (x,) = self.of("x", "off_platform")
        self.assertEqual((x["title"], x["url"]), ("Acme Outdoor", "https://acme.example/shoes"))
        self.assertIn("visited its site", x["text"])
        settings = [r for r in self.recs["facebook_activity"] if r["meta"].get("file") == "your_activity_off_meta_technologies_settings"]
        self.assertEqual(len(settings), 1, "the settings file is still kept as it was")

    def test_ads_you_were_shown_and_why(self):
        (ig,) = self.of("instagram_activity", "ad")
        self.assertEqual(ig["title"], "Acme Outdoor")
        self.assertIn("New trail shoes are here", ig["text"])
        (x,) = self.of("x", "ad")
        self.assertEqual(x["title"], "Corner Bakery")
        self.assertEqual(x["meta"]["why"], ["Locations: Chicago", "Age: 25 to 34"])
        self.assertFalse(any("personalization" in (r.get("meta") or {}).get("file", "") for r in self.recs.get("x_other", [])), "read, not left over")


if __name__ == "__main__":
    unittest.main()
