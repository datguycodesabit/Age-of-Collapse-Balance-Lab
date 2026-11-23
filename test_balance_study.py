import json
import unittest

from adaptive_route import adaptive_action, pick_plan
from agent_match import AgentMatch
from balance_study import analyze, lineup, route_record, summarize_routes
from engine import board_from, settings_from
from tune_sites import ROUTES
from tune_turn_length import PRESET


class StrategyStudyTests(unittest.TestCase):
    def setUp(self):
        self.preset=json.loads(PRESET.read_text())
        self.settings=settings_from(self.preset['settings'])
        self.board=board_from(self.preset['board'])

    def test_anchor_rotates_and_stays_a_shallow_farmer(self):
        for rotating in (False,True):
            anchors=set()
            for game in range(15):
                depths,anchor=lineup(game,rotating)
                self.assertEqual(depths[anchor],1)
                self.assertEqual(len(depths),5)
                anchors.add(anchor)
            self.assertEqual(len(anchors),5)

    def test_adaptive_policy_switches_when_boss_and_return_change(self):
        match=AgentMatch(self.preset['settings'],self.preset['board'])
        player=match.players[0]
        player.position=match.board.farms[2]
        player.energy=2
        match.round=8
        outbound=pick_plan(match)
        self.assertNotEqual(outbound.goal,match.board.start)
        match.round=13
        match.boss_events.append(dict(active_zone=3))
        retreat=pick_plan(match)
        self.assertEqual(retreat.goal,match.board.start)
        actions=match.legal_actions(0)
        self.assertIn(adaptive_action(match,retreat,actions,ROUTES[2]),actions)

    def test_funnel_counts_only_banks_after_mining_and_tracks_qualification(self):
        match=AgentMatch(self.preset['settings'],self.preset['board'])
        player=match.players[0]
        player.bank=7
        rows=[dict(turn=2,action='Delve',end_depth=2,farm_zone=0,draw_count=0,banked_now=0),
              dict(turn=3,action='Retreat',end_depth=0,farm_zone=0,draw_count=0,banked_now=7),
              dict(turn=5,action='Mine',end_depth=2,farm_zone=2,draw_count=1,banked_now=0)]
        sample=route_record(player,rows,2,15,0)
        self.assertEqual((sample['entered'],sample['mined'],sample['banked'],sample['score']),(2,5,None,0))
        player.escaped=True
        rows.append(dict(turn=7,action='Retreat',end_depth=0,farm_zone=0,draw_count=0,banked_now=2))
        sample=route_record(player,rows,2,15,1)
        self.assertEqual((sample['banked'],sample['surface'],sample['score']),(7,15,7))

    def test_comparison_is_seeded_and_pairs_same_route_cohorts(self):
        progress=[]
        study=analyze(self.settings,dict(games=5),self.board,progress.append)
        self.assertEqual(study,analyze(self.settings,dict(games=5),self.board))
        self.assertEqual(progress[-1]['done'],progress[-1]['total'])
        self.assertEqual(len(study['gear']),9)
        self.assertEqual({row['item'] for row in study['gear']},{'Boots','Sword','Shield'})
        for comparison in study['comparisons']:
            self.assertTrue(comparison['examples'])
            for fixed,adaptive in zip(comparison['fixed'],comparison['adaptive']):
                self.assertEqual(fixed['players'],adaptive['players'])
                self.assertAlmostEqual(adaptive['delta'],adaptive['score']-fixed['score'])
                self.assertIsNotNone(fixed['score_ci'][0])
                for route in (fixed,adaptive):
                    counts=[stage['count'] for stage in route['funnel'].values()]
                    self.assertEqual(counts,sorted(counts,reverse=True))
        with self.assertRaises(InterruptedError):
            analyze(self.settings,dict(games=5),self.board,cancel=lambda: True)

    def test_clusters_produce_intervals_for_scores_and_wins(self):
        def row(score,win):
            return dict(score=score,win=win,escaped=bool(score),
                        entered=1,mined=2,banked=None,surface=None)
        results=[{1:[row(4,0)],2:[row(8,1)],3:[row(0,0)]},
                 {1:[row(8,1)],2:[row(6,0)],3:[row(0,0)]}]
        shallow,_,deep=summarize_routes(results)
        self.assertEqual(shallow['score'],6)
        self.assertLess(shallow['score_ci'][0],6)
        self.assertGreater(deep['win_ci'][1],0)
