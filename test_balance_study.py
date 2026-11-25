from collections import Counter
from dataclasses import replace
import json
import unittest

from adaptive_route import STYLES, Plan, adaptive_action, bot_lineup, mine_line, pick_plan
from agent_match import AgentMatch
from balance_study import analyze, lineup, route_record, summarize_routes
from engine import board_from, settings_from, shared_game
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

    def test_personalities_rotate_and_restore_the_next_decision(self):
        lineups = [bot_lineup(seed, 5) for seed in range(30)]
        self.assertTrue(all(len({profile.style for profile in lineup}) == 5 for lineup in lineups))
        self.assertEqual(len({profile for lineup in lineups for profile in lineup}), 20)
        self.assertTrue(all(len({profile.style for profile in lineup[:3]}) == 3 for lineup in lineups))
        self.assertEqual(len(set(bot_lineup(42, 8))), 8)

        match = AgentMatch(dict(self.preset['settings'], bot_lookahead=4), self.preset['board'])
        action = adaptive_action(match, pick_plan(match), match.legal_actions(match.active))
        self.assertTrue(match.submit(dict(actor=match.active, revision=match.revision, action=action))['accepted'])
        saved = json.loads(json.dumps(match.serialize()))
        restored = AgentMatch.restore(saved)
        self.assertEqual(restored.settings.bot_lookahead, 4)
        for game in (match, restored):
            observation = game.serialize()
            choices = game.legal_actions(game.active)
            decision = adaptive_action(game, pick_plan(game), choices)
            self.assertIn(decision, choices)
            self.assertEqual(observation, game.serialize())
        self.assertEqual(pick_plan(match), pick_plan(restored))
        self.assertEqual(adaptive_action(match, pick_plan(match), match.legal_actions(match.active)),
                         adaptive_action(restored, pick_plan(restored), restored.legal_actions(restored.active)))

    def test_lookahead_credits_a_refill_and_compares_risk_to_a_safe_return(self):
        for difficulty in (0, 5, 1.5):
            with self.assertRaises(ValueError):
                settings_from(dict(self.preset['settings'], bot_lookahead=difficulty))
        match = AgentMatch(self.preset['settings'], self.preset['board'])
        player = match.players[0]
        banker = STYLES[0]
        easy = mine_line(match.settings, player, banker, 1, 2, 3, 2, 2, 1, 1, 0, 3)
        deeper = mine_line(match.settings, player, banker, 2, 2, 3, 2, 2, 1, 1, 0, 3)
        self.assertEqual(deeper[1], 1)
        self.assertGreater(deeper[0], easy[0])
        clear = mine_line(match.settings, player, banker, 1, 2, 1, 1, 2, 1, 1, 0, 3)
        danger = mine_line(match.settings, player, banker, 1, 2, 1, 1, 2, 1, 1, 1, 3)
        self.assertEqual(clear[1], 0)
        self.assertGreater(clear[0], danger[0])

    def test_banker_returns_earlier_and_duelist_can_interrupt_mining(self):
        rolled = json.loads(PRESET.with_name('rolled_combat_playtest.json').read_text())
        for style in ('Banker', 'Delver', 'Duelist', 'Prospector'):
            seed = next(seed for seed in range(100) if bot_lineup(seed, 5)[0].style == style)
            match = AgentMatch(dict(rolled['settings'], seed=seed), rolled['board'])
            player = match.players[0]
            player.position = (0, 2)
            player.energy = 10
            if style in ('Banker', 'Delver'):
                player.loot = 7
                player.treasures = [4, 3]
                self.assertEqual(pick_plan(match).goal == match.board.start, style == 'Banker')
            else:
                match.players[1].position = (1, 2)
                match.players[1].energy = 5
                actions = match.legal_actions(0)
                action = adaptive_action(match, Plan(player.position, 'Test farm'), actions)
                self.assertIn(action, actions)
                self.assertEqual(action['kind'], 'AttackPlayer' if style == 'Duelist' else 'Mine')

    def test_boss_hunter_prepares_for_a_favorable_fight(self):
        rolled = json.loads(PRESET.with_name('rolled_combat_playtest.json').read_text())
        for style in ('Boss Hunter', 'Prospector'):
            seed = next(seed for seed in range(100) if bot_lineup(seed, 5)[0].style == style)
            match = AgentMatch(dict(rolled['settings'], seed=seed), rolled['board'])
            match.round = match.settings.boss_start - 2
            player = match.players[0]
            player.position = (1, 8)
            player.energy = 10
            player.sword = player.shield = 3
            player.equipment.add('Boots')
            actions = match.legal_actions(0)
            action = adaptive_action(match, Plan(player.position, 'Test mine'), actions)
            self.assertIn(action, actions)
            self.assertEqual(action['kind'], 'Move' if style == 'Boss Hunter' else 'Mine')

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
        self.assertIn(adaptive_action(match,retreat,actions),actions)

    def test_default_simulation_mines_where_deck_odds_pay_off(self):
        def draws(settings):
            totals = Counter()
            for trial in range(4):
                _, players = shared_game(settings, self.board, trial, 5, None)
                for player in players:
                    for row in player['rows']:
                        if row['farm_zone']:
                            totals[row['farm_zone']] += row['draw_count']
            return totals

        rich = replace(self.settings, treasure_min2=30, treasure_max2=30)
        rare = replace(rich, deck_treasures2=1)
        rich_draws = draws(rich)
        self.assertGreater(rich_draws[2], rich_draws[1] + rich_draws[3])
        self.assertGreater(rich_draws[2], draws(self.settings)[2])
        self.assertGreater(rich_draws[2], draws(rare)[2])
        self.assertEqual(draws(replace(rich, max_zone=1))[2], 0)

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
