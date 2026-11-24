"""Behavior and replay tests for the opt-in expedition combat rules."""
import copy
from fractions import Fraction
from itertools import product
from math import prod
import unittest

from agent_match import AgentMatch
from dice_rules import award, combat_choice
from engine import settings_from
from model import moving_boss_round
from test_dice_rules import Rolls, play


OPEN_LAYOUT = dict(gates=[0, 0, 0], rows=['......'] * 10)


class ExpeditionCombatTests(unittest.TestCase):
    def match(self, **settings):
        config = dict(dice_rules=1, player_duels=1, moving_boss=1,
                      full_energy_moves=1, players=3, start_energy=10)
        return AgentMatch(dict(config, **settings), OPEN_LAYOUT)

    def test_exact_front_probabilities_and_shifted_arrival(self):
        settings = settings_from(dict(dice_rules=1, moving_boss=1))
        faces = range(1, 7)
        chances = [
            Fraction(sum(bool(moving_boss_round(settings, Rolls(die), turn, ())['collapse'])
                         for die in faces), 6)
            for turn in range(12, 17)
        ]
        self.assertEqual(chances, [Fraction(n, 6) for n in (2, 3, 4, 5, 5)])
        seal = sum(prod(p if win else 1-p for p, win in zip(chances, outcomes))
                   for outcomes in product((True, False), repeat=4) if sum(outcomes) >= 3)
        self.assertEqual(seal, Fraction(47, 108))
        shifted = self.match(boss_start=4).settings
        self.assertEqual(moving_boss_round(shifted, Rolls(), 3, ())['die'], 0)
        self.assertEqual(moving_boss_round(shifted, Rolls(5), 4, ())['collapse'], 3)

    def test_boss_uses_relocated_gates_and_one_roll_per_round(self):
        match = AgentMatch(dict(dice_rules=1, moving_boss=1, boss_start=1, players=2),
                           dict(OPEN_LAYOUT, gates=[2, 4, 1]))
        match.boss_rng = Rolls(4, 4, 3, 2)
        self.assertEqual(match.observation(0)['boss']['tile'], (1, 7))
        self.assertEqual(match.observation(0)['boss_events'], [])
        play(match, 'EndTurn')
        self.assertEqual(match.boss_events, [])
        play(match, 'EndTurn')
        self.assertEqual((match.round, match.closed), (2, ()))
        self.assertEqual(match.boss_events[0]['die'], 4)
        for expected in ((3,), (2, 3), (1, 2, 3)):
            play(match, 'EndTurn')
            play(match, 'EndTurn')
            self.assertEqual(match.closed, expected)
        self.assertEqual(match.boss_events[1]['tile_after'], (4, 4))
        self.assertEqual(match.boss_events[2]['tile_after'], (2, 1))
        self.assertIsNone(match.observation(0)['boss'])

    def test_rejected_or_queried_combat_preserves_rng_and_state(self):
        match = self.match(boss_start=1)
        match.players[0].position = (0, 6)
        match.players[1].position = (1, 6)
        match.players[1].energy = 0
        match.players[2].position = (0, 7)
        initial = match.observation(0)
        saved = match.serialize()
        rngs = [match.duel_rng, match.boss_combat_rng, match.boss_rng, *match.combat_rngs]
        rng_states = [rng.getstate() for rng in rngs]
        for action in ({'kind': 'AttackBoss'}, {'kind': 'AttackBoss', 'target': 2},
                       {'kind': 'AttackPlayer', 'target': 0}, {'kind': 'AttackPlayer', 'target': 1},
                       {'kind': 'AttackPlayer', 'target': 2}, {'kind': 'AttackPlayer', 'target': True}):
            self.assertFalse(match.submit(dict(actor=0, revision=0, action=action))['accepted'])
        self.assertEqual(match.observation(0), initial)
        self.assertEqual(match.serialize(), saved)
        self.assertEqual([rng.getstate() for rng in rngs], rng_states)

    def test_duel_transfers_entire_hand_and_skips_defenders_turn(self):
        match = self.match()
        first, second, _ = match.players
        first.position, second.position = (0, 2), (1, 2)
        first.sword, second.shield = 1, 2
        first.items['Bow'] = 1
        first.grenade_armed = True
        second.energy = 4
        second.bank_cards = [9]
        second.bank = 9
        award(first, 1)
        award(second, 3)
        award(second, 0)
        award(second, 8)
        match.duel_rng = Rolls(2)
        result = play(match, 'AttackPlayer', target=1)
        self.assertTrue(result['accepted'])
        fight = result['event']['duel']
        self.assertEqual((fight['winner'], fight['gold']), (0, 11))
        self.assertEqual(fight['exchanges'][0]['shield_absorbed'], 2)
        self.assertTrue(fight['exchanges'][0]['grenade'])
        self.assertFalse(first.grenade_armed)
        self.assertEqual((first.loot, first.treasures, first.energy), (12, [1, 3, 0, 8], 9))
        self.assertEqual((second.energy, second.loot, second.bank, second.position), (0, 0, 9, (0, 0)))
        self.assertEqual(match.logs[1][-1]['knockdown'], 'Yes')
        play(match, 'EndTurn')
        self.assertEqual(match.active, 2)
        play(match, 'EndTurn')
        play(match, 'EndTurn')
        self.assertEqual((match.round, match.active), (2, 1))

    def test_defender_can_win_and_minimum_damage_finishes_duel(self):
        match = self.match()
        first, second, _ = match.players
        first.position, second.position = (0, 1), (1, 1)
        first.shield = second.shield = 3
        first.energy, second.energy = 2, 2
        award(first, 4)
        match.duel_rng = Rolls(1, 1)
        row = play(match, 'AttackPlayer', target=1)['event']
        self.assertEqual([hit['damage'] for hit in row['duel']['exchanges']], [1, 1])
        self.assertEqual((row['duel']['winner'], match.active, second.loot), (1, 1, 4))

    def test_duel_journal_and_old_version_restore(self):
        match = self.match()
        play(match, 'Move', destination=[0, 1])
        play(match, 'EndTurn')
        play(match, 'Move', destination=[1, 1])
        self.assertTrue(play(match, 'AttackPlayer', target=0)['accepted'])
        restored = AgentMatch.restore(match.serialize())
        self.assertEqual(restored.observation(0), match.observation(0))
        self.assertEqual(restored.observation(1), match.observation(1))
        self.assertEqual(restored.duel_rng.getstate(), match.duel_rng.getstate())
        legacy = AgentMatch(dict(dice_rules=1))
        save = legacy.serialize()
        save['version'] = 3
        for key in ('moving_boss', 'player_duels', 'boss_hp', 'boss_attack', 'boss_hoard'):
            del save['settings'][key]
        self.assertEqual(AgentMatch.restore(save).observation(0), legacy.observation(0))

    def test_boss_heals_after_knockdown(self):
        match = self.match(boss_start=1, boss_attack=4, boss_hp=9)
        first, second, _ = match.players
        first.position, second.position = (0, 7), (1, 7)
        first.energy = 3
        award(first, 10)
        match.boss_combat_rng = Rolls(6, 3, 6)
        row = play(match, 'AttackBoss')['event']
        self.assertEqual((row['combat_events'][0]['exchanges'][0]['hp_left'], row['loot_penalty']), (3, 10))
        self.assertEqual((first.energy, first.position, match.active), (0, (0, 6), 1))
        self.assertEqual(match.boss_status()['hp'], 9)
        row = play(match, 'AttackBoss')['event']
        self.assertEqual(len(row['combat_events'][0]['exchanges']), 2)
        self.assertTrue(match.complete)

    def test_killer_and_surface_players_rank_by_bank_and_ties_share(self):
        for surface_bank, winners in ((34, [0]), (35, [0, 1]), (36, [1])):
            with self.subTest(surface_bank=surface_bank):
                match = self.match(boss_start=1, boss_hp=1)
                for point in ([0, 2], [0, 4], [0, 6], [0, 7]):
                    self.assertTrue(play(match, 'Move', destination=point)['accepted'])
                award(match.players[0], 10)
                match.players[1].bank = surface_bank
                match.players[2].position = (1, 1)
                match.players[2].bank = 100
                before_rng = match.boss_rng.getstate()
                self.assertEqual(combat_choice(match, match.legal_actions(0)),
                                 {'kind': 'AttackBoss'} if surface_bank <= 35 else None)
                row = play(match, 'AttackBoss')['event']
                view = match.observation(0)
                self.assertEqual((row['boss_hoard'], view['winners'], view['boss_defeated_by']),
                                 (35, winners, 0))
                self.assertTrue(view['complete'])
                self.assertFalse(play(match, 'EndTurn')['accepted'])
                self.assertEqual(match.players[0].loot, 10)
                self.assertEqual(match.players[0].bank_cards, [35])
                self.assertEqual((match.boss_events, match._schedule), ([], []))
                self.assertEqual(match.boss_rng.getstate(), before_rng)

    def test_boss_victory_replays_from_commands(self):
        match = self.match(boss_start=1, boss_hp=1)
        for point in ([0, 2], [0, 4], [0, 6], [0, 7]):
            play(match, 'Move', destination=point)
        play(match, 'AttackBoss')
        restored = AgentMatch.restore(copy.deepcopy(match.serialize()))
        for seat in range(3):
            self.assertEqual(restored.observation(seat), match.observation(seat))
        self.assertEqual(restored.boss_combat_rng.getstate(), match.boss_combat_rng.getstate())
