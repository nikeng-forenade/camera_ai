import unittest
from unittest.mock import patch

from fastapi.responses import JSONResponse

from app import get_events


class EventApiTests(unittest.TestCase):
    def test_events_are_newest_first_and_cache_disabled(self):
        with patch("app.EVENT_LOG", [{"id": "old"}, {"id": "new"}]):
            response = get_events(50)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b'[{"id":"new"},{"id":"old"}]')
        self.assertEqual(response.headers["cache-control"], "no-store, no-cache, must-revalidate")
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_limit_is_clamped_to_one_through_fifty(self):
        items = [{"id": str(index)} for index in range(60)]
        with patch("app.EVENT_LOG", items):
            one = get_events(0)
            fifty = get_events(100)

        # Båda körs med samma mockade logg så testet inte beror på data/events.json.
        expected_fifty = [dict(i) for i in items[-50:][::-1]]
        expected = JSONResponse(expected_fifty)
        self.assertEqual(one.body, b'[{"id":"59"}]')
        self.assertEqual(len(fifty.body), len(expected.body))


if __name__ == "__main__":
    unittest.main()
