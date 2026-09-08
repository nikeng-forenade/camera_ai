import unittest

from license_plate import PlateReader


class LicensePlateTests(unittest.TestCase):
    def test_normalize_plate_text(self):
        self.assertEqual(PlateReader.normalize(" abc-123 "), "ABC123")
        self.assertEqual(PlateReader.normalize("---"), "")
        self.assertEqual(PlateReader.normalize("AB"), "")


if __name__ == "__main__":
    unittest.main()