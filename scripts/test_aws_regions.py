import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import aws_regions  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class ExtractRegionsTest(unittest.TestCase):
    def setUp(self):
        self.regions = aws_regions.extract_regions(read_fixture("regions_az.html"))

    def test_flattens_all_regions_with_continent(self):
        self.assertEqual(len(self.regions), 15)
        malaysia = next(r for r in self.regions if r["name"] == "Asia Pacific (Malaysia)")
        self.assertEqual(malaysia["continent"], "Asia Pacific")
        self.assertEqual(malaysia["id"], "ap-southeast-5")

    def test_trims_whitespace(self):
        beijing = next(r for r in self.regions if "Beijing" in r["name"])
        self.assertEqual(beijing["id"], "cn-north-4")
        self.assertEqual(beijing["name"], "Mainland China (Beijing)")

    def test_missing_blob_raises(self):
        with self.assertRaises(aws_regions.ScrapeError):
            aws_regions.extract_regions("<html>redesigned</html>")


class MatchKeyTest(unittest.TestCase):
    def test_normalises(self):
        k = aws_regions.match_key
        self.assertEqual(k("US East (N. Virginia)"), k("US East (Northern Virginia)"))
        self.assertEqual(k("South America (Sao Paulo)"), k("South America (São Paulo)"))


class BuildTest(unittest.TestCase):
    def setUp(self):
        page = aws_regions.extract_regions(read_fixture("regions_az.html"))
        boto = aws_regions.load_botocore(read_fixture("endpoints.json"))
        self.regions = {r["name"]: r for r in aws_regions.merge(page, boto)}

    def test_corrects_wrong_page_ids(self):
        expected = {
            "Mainland China (Beijing)": ("cn-north-1", "aws-cn"),
            "Asia Pacific (Thailand)": ("ap-southeast-7", "aws"),
            "Asia Pacific (New Zealand)": ("ap-southeast-6", "aws"),
            "Asia Pacific (Taipei)": ("ap-east-2", "aws"),
            "AWS European Sovereign Cloud (Germany)": ("eusc-de-east-1", "aws-eusc"),
            "Australia (Melbourne)": ("ap-southeast-4", "aws"),
        }
        for name, (code, partition) in expected.items():
            self.assertEqual((self.regions[name]["code"], self.regions[name]["partition"]), (code, partition), name)

    def test_same_parenthetical_resolved_by_full_name(self):
        self.assertEqual(self.regions["Canada (Central)"]["code"], "ca-central-1")
        self.assertEqual(self.regions["Mexico (Central)"]["code"], "mx-central-1")
        self.assertEqual(self.regions["US East (Ohio)"]["code"], "us-east-2")  # not us-isob-east-1

    def test_announced_region_has_null_code(self):
        chile = self.regions["South America (Chile)"]
        self.assertIsNone(chile["code"])
        self.assertIsNone(chile["partition"])
        self.assertFalse(chile["available"])
        self.assertIsNone(chile["launched"])

    def test_output_fields(self):
        self.assertEqual(
            self.regions["Asia Pacific (Malaysia)"],
            {
                "code": "ap-southeast-5",
                "name": "Asia Pacific (Malaysia)",
                "continent": "Asia Pacific",
                "partition": "aws",
                "available": True,
                "availability_zones": 3,
                "launched": 2024,
                "lat": 3.139,
                "lng": 101.6869,
            },
        )


class GuardrailTest(unittest.TestCase):
    def setUp(self):
        self.page = aws_regions.extract_regions(read_fixture("regions_az.html"))
        self.boto = aws_regions.load_botocore(read_fixture("endpoints.json"))

    def test_too_few_regions_raises(self):
        regions = aws_regions.merge(self.page, self.boto)
        with self.assertRaises(aws_regions.ScrapeError):
            aws_regions.validate(regions, min_count=30)

    def test_duplicate_code_raises(self):
        regions = aws_regions.merge(self.page, self.boto)
        regions.append(dict(regions[0]))
        with self.assertRaises(aws_regions.ScrapeError):
            aws_regions.validate(regions, min_count=1)


class WriteTest(unittest.TestCase):
    def test_unchanged_regions_keep_timestamp(self):
        regions = [{"code": "us-east-1", "name": "US East (Northern Virginia)"}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            self.assertTrue(aws_regions.write_output(path, regions, now="2026-01-01T00:00:00Z"))
            self.assertFalse(aws_regions.write_output(path, regions, now="2026-02-01T00:00:00Z"))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["generated_at"], "2026-01-01T00:00:00Z")
            self.assertEqual(data["count"], 1)

            aws_regions.write_output(path, regions + [{"code": "us-east-2", "name": "US East (Ohio)"}], now="2026-03-01T00:00:00Z")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["generated_at"], "2026-03-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
