"""Seeded replay and equipment checks for the rolled enemy playtest."""
from collections import Counter
import json
import unittest

from agent_match import AgentMatch
from dice_rules import decks, fight, shield_block
from enemy_profiles import archetype_counts, boss_faces, odds_table
from engine import settings_from
from model import Player
from test_dice_rules import Rolls, play


class RolledEnemyTests(unittest.TestCase):
    def settings(self, **values):
        return settings_from(dict({'dice_rules': 1, 'rolled_enemy_attacks': 1,
                                   'sword_damage_bonus': 1}, **values))

    def test_decks_preserve_value_and_kind_order_and_split_monsters(self):
        rolled = self.settings(seed=54, deck_monsters1=1, deck_monsters2=2)
        before = decks(self.settings(seed=54, deck_monsters1=1, deck_monsters2=2, rolled_enemy_attacks=0))
        after = decks(rolled)
        for zone, pile in after.items():
            self.assertEqual([row[0] for row in before[zone]], [row[0] for row in pile])
            self.assertEqual([row for row in before[zone] if row[0] != 'Monster'],
                             [row for row in pile if row[0] != 'Monster'])
            self.assertEqual(Counter(card['archetype'] for kind, _, card in pile if kind == 'Monster'),
                             {name: count for name, count in zip(
                                 ('Balanced', 'Striker', 'Tank'),
                                 archetype_counts(getattr(rolled, f'deck_monsters{zone}'))) if count})
        self.assertEqual(after, decks(rolled))

    def test_zero_and_blocked_counters_roll_and_killing_blow_does_not(self):
        player = Player(energy=0, shield=1, sword=0)
        rolls = Rolls(1, 1, 1, 2, 6)
        hits, fell = fight(player, self.settings(), rolls, 1, 4, attack_faces=(0, 2, 2, 3, 4, 5))
        self.assertFalse(fell)
        self.assertEqual([(hit['enemy_roll'],hit['raw_attack'],hit['shield_absorbed'],hit['hit']) for hit in hits],
                         [(1, 0, 0, 0), (2, 2, 2, 0), (None, 0, 0, 0)])
        with self.assertRaises(StopIteration):
            rolls.randint(1, 6)

    def test_trials_hit_striker_targets_and_other_types_reward_different_gear(self):
        for row in odds_table(self.settings()):
            if row['energy'] != 2:
                continue
            no_gear, sword, shield, both = row['wins']
            if row['archetype'] == 'Striker':
                for actual,target in zip((no_gear,sword,shield),(.20,.50,.75)):
                    self.assertLessEqual(abs(actual-target), .07)
            elif row['archetype'] == 'Tank':
                self.assertGreaterEqual(sword-shield, .10)
            else:
                self.assertLessEqual(abs(sword-shield), .10)
            self.assertGreaterEqual(both, max(sword,shield))

    def test_rolled_duel_uses_the_same_gear(self):
        match = AgentMatch(dict(dice_rules=1, player_duels=1, rolled_enemy_attacks=1, players=2))
        first, second = match.players
        first.position, second.position = (0, 1), (1, 1)
        first.energy, second.energy = 5, 1
        second.shield = 3
        match.duel_rng = Rolls(6)
        row = play(match, 'AttackPlayer', target=1)['event']
        self.assertEqual(row['duel']['exchanges'][0]['shield_absorbed'], 5)
        self.assertEqual(shield_block(match.settings, 3), 5)

    def test_rolled_boss_uses_its_own_rng_and_preserves_scoring(self):
        match = AgentMatch(dict(dice_rules=1, moving_boss=1, rolled_enemy_attacks=1, boss_start=1,
                                boss_hp=7, start_energy=10, players=2))
        match.players[0].position = match.board.entrance(3)
        match.boss_combat_rng = Rolls(1, 5, 6)
        rng = match.boss_rng.getstate()
        row = play(match,'AttackBoss')['event']
        fight_log = row['combat_events'][0]['exchanges']
        self.assertEqual((fight_log[0]['enemy_roll'], fight_log[0]['raw_attack']), (5, 7))
        self.assertIsNone(fight_log[1]['enemy_roll'])
        self.assertEqual(sum(boss_faces(match.settings)), 24)
        self.assertTrue(row['boss_defeated'])
        self.assertEqual(match.observation(0)['winners'], [0])
        self.assertEqual(match.boss_rng.getstate(), rng)

    def test_mining_journal_replays_and_version_four_stays_fixed(self):
        board = dict(gates=[0,0,0], rows=['......','M.....',*['......']*8])
        config = dict(dice_rules=1, rolled_enemy_attacks=1, deck_monsters1=40,
                      deck_treasures1=0, full_energy_moves=1, start_energy=6)
        match = next(match for seed in range(10) if
                     (match := AgentMatch(dict(config, seed=seed),board)).decks[1][0][0]=='Monster')
        self.assertTrue(play(match,'Move',destination=[0,1])['accepted'])
        success = play(match,'Mine')['event']
        self.assertIn('enemy_roll', success['combat_events'][0]['exchanges'][0])
        restored = AgentMatch.restore(json.loads(json.dumps(match.serialize())))
        self.assertEqual(restored.observation(0), match.observation(0))
        self.assertEqual(restored.combat_rngs[0].getstate(), match.combat_rngs[0].getstate())
        old = AgentMatch(dict(config, rolled_enemy_attacks=0),board).serialize()
        old['version'] = 4
        for key in ('rolled_enemy_attacks','boss_challenge_pct','monster_profiles'):
            del old['settings'][key]
        legacy = AgentMatch.restore(old)
        player = Player(energy=4, sword=0)
        hits,_ = fight(player,legacy.settings,Rolls(1,6),1,3)
        self.assertNotIn('enemy_roll',hits[0])
        self.assertEqual(hits[0]['hit'],legacy.settings.atk1)

    def test_custom_profiles_are_validated_before_play(self):
        data = self.settings().monster_profiles
        data['1']['Tank']['faces'] = [0, 1, 2, 3, 4]
        with self.assertRaisesRegex(ValueError,'six whole numbers'):
            self.settings(monster_profiles=data)
