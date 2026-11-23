"""Behavioral checks for the shared-zone rules."""
from collections import Counter
import copy
import json
import unittest

from agent_match import AgentMatch
from engine import experiment, settings_from
from zone_decks import COMPOSITION, ITEMS, shuffled_decks


def play(match, kind, **fields):
    return match.submit(dict(actor=match.active,revision=match.revision,
                             action=dict(kind=kind,**fields)))


class ZoneDeckTests(unittest.TestCase):
    def match(self, **settings):
        return AgentMatch(dict(shared_decks=1,players=2,boss_enabled=0,**settings))

    def test_exact_decks_and_seed_order(self):
        decks=shuffled_decks(42)
        self.assertEqual(decks,shuffled_decks(42))
        self.assertNotEqual(decks,shuffled_decks(43))
        for zone,pile in decks.items():
            self.assertEqual(len(pile),50)
            counts=Counter(card[0] for card in pile)
            self.assertEqual({kind:counts[kind] for kind in COMPOSITION[zone]},COMPOSITION[zone])
        self.assertEqual({name for pile in decks.values() for kind,name in pile if kind=='Item'},set(ITEMS))
        self.assertEqual(len({name for kind,name in decks[1] if kind=='Monster'}),10)

    def test_seats_draw_from_one_pile_and_combat_resolves_before_next_card(self):
        match=self.match()
        match.decks[1]=[('Monster','Spider'),('Treasure','Amber')]
        original=copy.deepcopy(match.decks)
        match.legal_actions(0)
        self.assertFalse(play(match,'Move',destination=[0,8])['accepted'])
        self.assertEqual(match.decks,original)
        row=play(match,'Move',destination=[0,1])['event']
        self.assertEqual(row['combat_events'][0]['target'],'Spider')
        self.assertEqual(row['combat_cost'],4)
        play(match,'EndTurn')
        self.assertEqual(play(match,'Move',destination=[0,1])['event']['drawn'],['Amber'])
        self.assertEqual(match.observation(0)['deck_remaining'][1],0)
        self.assertEqual(match.players[1].treasures,[2])
        self.assertEqual(play(match,'Move',destination=[0,2])['event']['draw_count'],0)

        match=self.match()
        match.players[0].position=match.board.farms[0]
        match.players[0].energy=2
        match.decks[1]=[('Monster','Spider'),('Item','Bow')]
        row=play(match,'Mine')['event']
        self.assertEqual((row['knockdown'],row['draw_count']),('Yes',1))
        self.assertEqual(match.decks[1],[('Item','Bow')])

    def test_pickaxe_is_private_and_leaves_unchosen_card_on_top(self):
        match=self.match()
        p=match.players[0]
        p.position=match.board.farms[0]
        p.items['Pickaxe']=1
        match.decks[1]=[('Monster','Spider'),('Treasure','Amber'),('Nothing','Dust')]
        self.assertTrue(play(match,'Use',item='Pickaxe')['accepted'])
        self.assertEqual(match.observation(0)['you']['pick_options'][:2],match.decks[1][:2])
        self.assertEqual(match.observation(1)['you']['pick_options'],[])
        self.assertFalse(play(match,'EndTurn')['accepted'])
        result=play(match,'Mine',pick=1)
        self.assertEqual(result['event']['drawn'],['Amber'])
        self.assertEqual(match.decks[1][0],('Monster','Spider'))
        self.assertEqual(p.treasures,[2])
        self.assertNotIn({'kind':'Mine'},match.legal_actions(0))

    def test_shop_upgrades_coupon_and_combat_equipment(self):
        match=self.match()
        p=match.players[0]
        p.items.update(Coupon=1,Bow=1,Grenade=1)
        p.treasures=[2,4]
        p.loot=6
        self.assertTrue(play(match,'Buy',item='Sword')['accepted'])
        self.assertTrue(play(match,'Buy',item='Shield')['accepted'])
        self.assertEqual((p.sword,p.shield,p.loot),(2,1,0))
        self.assertTrue(play(match,'Use',item='Grenade')['accepted'])
        match.decks[1]=[('Monster','Spider')]
        row=play(match,'Move',destination=[0,1])['event']
        self.assertEqual(row['combat_cost'],0)
        self.assertTrue(row['combat_events'][0]['ranged'])
        self.assertFalse(p.grenade_armed)

    def test_shovel_and_player_targeted_items(self):
        match=self.match(gain=8)
        p,other=match.players
        p.position=match.board.farms[0]
        p.items.update({'Shovel':1,'Teleport Potion':1,'Thief’s Tools':1})
        other.position=(0,2)
        other.treasures=[2]
        other.loot=2
        match.decks[1]=[('Treasure','Opal'),('Treasure','Amber')]
        self.assertTrue(play(match,'Use',item='Thief’s Tools',target=1)['accepted'])
        self.assertFalse(play(match,'Use',item='Teleport Potion',target=1,destination=[0,4])['accepted'])
        self.assertTrue(play(match,'Use',item='Teleport Potion',target=1,destination=[1,3])['accepted'])
        self.assertEqual((other.position,other.loot),((1,3),0))
        row=play(match,'Use',item='Shovel')['event']
        self.assertEqual((row['draw_count'],row['action_cost'],p.loot),(2,2,6))
        self.assertEqual(p.items['Shovel'],0)

    def test_energy_items_charges_and_temporal_effects(self):
        match=self.match()
        p=match.players[0]
        p.items.update({'Energy Potion':1,'Speed Potion':1,'Energy Canister':1})
        p.energy=5
        self.assertEqual(play(match,'Use',item='Energy Potion')['event']['bonus'],3)
        self.assertTrue(play(match,'Use',item='Speed Potion')['accepted'])
        row=play(match,'Move',destination=[1,0])['event']
        self.assertEqual(row['action_cost'],.5)
        p.energy=0
        play(match,'EndTurn')
        play(match,'EndTurn')
        self.assertEqual(p.energy,7)

    def test_seeded_journal_and_experiment_reproduce_shared_draws(self):
        match=self.match()
        for _ in range(5):
            play(match,'Move',destination=[0,1])
            if match.active is not None:
                play(match,'EndTurn')
        restored=AgentMatch.restore(json.loads(json.dumps(match.serialize())))
        self.assertEqual(restored.decks,match.decks)
        self.assertEqual(restored.observation(0),match.observation(0))

        config=settings_from(dict(shared_decks=1,runs=1,players=4))
        result=experiment(config)
        self.assertEqual(result,experiment(config))
        draws=Counter()
        for sample in result['samples']:
            for row in sample['rows']:
                draws.update({row['zone']:row['draw_count']})
        self.assertTrue(draws)
        self.assertTrue(all(count<=50 for count in draws.values()))
        self.assertEqual(result['metrics']['player_runs'],4)
