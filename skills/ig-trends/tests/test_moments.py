"""Tests for moments.py. Stdlib only, no network: the pages are fixtures.

Run from the skill folder:  python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import moments  # noqa: E402

NOW = 1792218900.0          # Sat Oct 17 2026 06:35 UTC


def snap(ts, names):
    lis = "".join(f'<li><span class=trend-name><a href="https://twitter.com/search?q=x" class=trend-link>{n}</a>'
                  f'<span class=tweet-count data-count=""></span></span></li>' for n in names)
    return (f'<div class=list-container><h3 class=title data-timestamp={ts}>t</h3>'
            f'<ol class=trend-card__list>{lis}</ol></div>')


X_HTML = "<html>" + "".join(
    snap(NOW - h * 3600, ["#Deva", "Tesla" if h < 18 else "London", "Jio IPO", "Tesla Roadster" if h in (3, 4) else "Garba"])
    for h in range(24)) + snap(NOW - 30 * 3600, ["Old thing"]) + "</html>"

NEWS = """<?xml version="1.0"?><rss><channel>
<item><title>With flying Roadster, Tesla waves goodbye to the car business - Axios</title><source>Axios</source>
<pubDate>Sat, 17 Oct 2026 05:00:00 GMT</pubDate></item>
<item><title>Ambani taps workforce to boost Jio&#39;s record IPO - Bloomberg</title><source>Bloomberg</source></item>
<item><title>Something else entirely - BBC</title><source>BBC</source></item>
</channel></rss>"""


class TestParse(unittest.TestCase):
    def test_x_snapshots_last_24h_only(self):
        snaps = moments.parse_x(X_HTML, NOW)
        self.assertEqual(len(snaps), 24)
        self.assertEqual(snaps[0][1][0], "#Deva")
        self.assertNotIn("Old thing", [n for _, ns in snaps for n in ns])

    def test_news_strips_source_suffix(self):
        items = moments.parse_news(NEWS)
        self.assertEqual(items[0]["title"], "With flying Roadster, Tesla waves goodbye to the car business")
        self.assertEqual(items[1]["title"], "Ambani taps workforce to boost Jio's record IPO")
        self.assertEqual(moments.parse_news("not xml"), [])

    def test_hashtag_words(self):
        self.assertEqual(moments.words("#TeslaRoadster launch"), ["tesla", "roadster", "launch"])


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.r = moments.run("IN", x_html=X_HTML, news_rss=NEWS, now=NOW)

    def test_in_the_news_and_on_x_comes_first(self):
        names = [m["name"] for m in self.r["moments"]]
        self.assertEqual(set(names[:2]), {"Tesla Roadster", "Jio IPO"})
        self.assertTrue(all(m["moment"] for m in self.r["moments"][:2]))
        self.assertFalse(next(m for m in self.r["moments"] if m["name"] == "#Deva")["moment"])

    def test_tesla_and_tesla_roadster_are_one_moment(self):
        names = [m["name"] for m in self.r["moments"]]
        self.assertNotIn("Tesla", names)
        tesla = next(m for m in self.r["moments"] if m["name"] == "Tesla Roadster")
        self.assertEqual(tesla["hours"], 18)                  # the longer run of the two
        self.assertIn("flying Roadster", tesla["news"][0])

    def test_offline_never_touches_the_network(self):
        self.assertEqual(self.r["snapshots"], 24)
        self.assertEqual(self.r["notes"], [])

    def test_render(self):
        import io
        buf = io.StringIO()
        moments.render(self.r, buf)
        self.assertIn("MOMENT", buf.getvalue())
        self.assertIn("18h on X", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
