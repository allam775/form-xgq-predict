"""Verify the independent UI wiring without browser or fabricated sports data."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]

class IdReader(HTMLParser):
    def __init__(self):super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])

class SiteContractTests(unittest.TestCase):
    def test_every_js_target_is_in_html_and_ids_unique(self):
        parser=IdReader();parser.feed((ROOT/'site/index.html').read_text())
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        targets=set(re.findall(r"\$\('([a-z-]+)'\)",(ROOT/'site/app.js').read_text()))
        self.assertTrue(targets)
        self.assertFalse(targets-set(parser.ids),f'Missing UI IDs: {targets-set(parser.ids)}')
    def test_no_fictitious_sample_probabilities_in_page(self):
        page=(ROOT/'site/index.html').read_text()
        self.assertNotIn('54%',page)
        self.assertNotIn('Demo predictions',page)
        self.assertIn('not predictions',page)
        self.assertIn('id="unavailable-list"',page)
if __name__=='__main__':unittest.main()
