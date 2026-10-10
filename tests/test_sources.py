"""Unit tests for automatic discovery of the free StatsBomb competition catalog."""
import unittest
from engine.collect import choose_open_seasons

class OpenSeasonTests(unittest.TestCase):
    def test_recent_seasons_chosen_and_interleaved(self):
        data=[
            {'competition_id':11,'season_id':90,'season_name':'2020/2021'},
            {'competition_id':11,'season_id':42,'season_name':'2019/2020'},
            {'competition_id':11,'season_id':4,'season_name':'2018/2019'},
            {'competition_id':9,'season_id':281,'season_name':'2023/2024'},
            {'competition_id':2,'season_id':27,'season_name':'2015/2016'},
            {'competition_id':77,'season_id':321,'season_name':'2025/2026'}]
        result=choose_open_seasons(data)
        self.assertEqual(set(result),{(11,90),(11,42),(9,281),(2,27)})
        self.assertEqual(result.count((11,90)),1)
        self.assertEqual(result[-1],(11,42))
    def test_missing_season_or_unknown_competition_never_selected(self):
        self.assertEqual(choose_open_seasons([{'competition_id':11,'season_id':90,'season_name':'Unknown'}]),[])
        self.assertEqual(choose_open_seasons([{'competition_id':53,'season_id':90,'season_name':'2025/2026'}]),[])
    def test_no_more_than_two_per_league(self):
        records=[{'competition_id':11,'season_id':i,'season_name':f'{2017+i}/{2018+i}'} for i in range(5)]
        self.assertEqual(len(choose_open_seasons(records)),2)
    def test_invalid_records_ignored(self):
        self.assertEqual(choose_open_seasons([None,'bad',{'competition_id':11,'season_id':'90','season_name':'2024/2025'}]),[])

if __name__=='__main__':unittest.main()
