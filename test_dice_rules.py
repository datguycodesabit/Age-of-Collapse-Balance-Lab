"""Behavior checks for the dice mode and its original-journal compatibility."""
import copy
import json
import unittest
from collections import Counter

from agent_match import AgentMatch
from dice_rules import deck_composition, decks, fight
from engine import experiment, settings_from
from model import Player, neighbors
from zone_decks import COMPOSITION


class Rolls:
    def __init__(self, *rolls):
        self.rolls=iter(rolls)

    def randint(self,low,high):
        return next(self.rolls)


def play(match,kind,**fields):
    return match.submit(dict(actor=match.active,revision=match.revision,
                             action=dict(kind=kind,**fields)))


class DiceRulesTests(unittest.TestCase):
    def match(self, **settings):
        return AgentMatch(dict(dice_rules=1,boss_enabled=0,**settings))

    def test_movement_opens_every_gate_and_never_draws(self):
        with self.assertRaisesRegex(ValueError,'cap Energy at 10'):
            self.match(players=1,cap=11)
        match=self.match(players=1)
        p=match.players[0]
        self.assertEqual((p.energy,p.sword,p.shield),(2,0,0))
        p.energy=10
        p.position=match.board.exit(2)
        deck_before=copy.deepcopy(match.decks)
        result=play(match,'Move',destination=list(match.board.entrance(3)))
        self.assertTrue(result['accepted'])
        self.assertEqual((p.energy,result['event']['draw_count']),(9.5,0))
        self.assertEqual(match.decks,deck_before)
        self.assertTrue(play(match,'EndTurn')['accepted'])
        self.assertEqual(p.energy,10)

    def test_full_energy_move_cost_and_multi_square_replay(self):
        for destination in ([0,1],[0,2]):
            match=self.match(players=1,full_energy_moves=1,start_energy=1)
            rejected=play(match,'Move',destination=[0,3])
            self.assertFalse(rejected['accepted'])
            self.assertEqual(match.revision,0)
            result=play(match,'Move',destination=destination)
            self.assertTrue(result['accepted'])
            row=result['event']
            self.assertEqual((row['action_cost'],row['end_energy'],row['move_steps'],row['draw_count']),
                             (1,0,destination[1],0))
            self.assertFalse(play(match,'Move',destination=[1,destination[1]])['accepted'])
            self.assertEqual(AgentMatch.restore(match.serialize()).observation(0),match.observation(0))

    def test_full_energy_move_can_pass_pawns_and_pick_up_gate_tonic_en_route(self):
        match=self.match(players=2,full_energy_moves=1,start_energy=1)
        p,other=match.players
        p.position=(0,6)
        other.position=(0,7)
        self.assertFalse(play(match,'Move',destination=[0,7])['accepted'])
        self.assertFalse(play(match,'Move',destination=[1,8])['accepted'])
        result=play(match,'Move',destination=[0,8])
        self.assertTrue(result['accepted'])
        self.assertEqual((p.position,p.energy,p.potions),((0,8),0,{'Energy Tonic':1}))
        self.assertIn((0,7),p.visited)

    def test_move_gate_and_mine_two_distinct_farms_in_one_turn(self):
        board=dict(gates=[2,4,1],rows=['......','..F...','..F...',*['......']*7])
        match=AgentMatch(dict(dice_rules=1,boss_enabled=0,players=1,
                              farm_shared_limit=1,start_energy=10,full_energy_moves=1),board)
        player=match.players[0]
        self.assertEqual(player.position,(2,0))
        self.assertNotIn((0,1),neighbors((0,0),(),match.board))
        self.assertIn((4,4),neighbors((4,3),(),match.board))
        self.assertIn((1,7),neighbors((1,6),(),match.board))
        wrong=play(match,'Move',destination=[0,1])
        self.assertFalse(wrong['accepted'])
        self.assertEqual(match.revision,0)
        match.decks[1]=[('Nothing','Nothing',None)]*6
        for destination in ([2,1],[2,2]):
            self.assertTrue(play(match,'Move',destination=destination)['accepted'])
            event=play(match,'Mine')['event']
            self.assertEqual((event['action'],event['draw_count'],event['action_cost']),('Farm',2,2))
            self.assertFalse(play(match,'Mine')['accepted'])
        self.assertEqual(match.farm_uses,{(2,1):1,(2,2):1})
        self.assertEqual(len(match.decks[1]),2)

    def test_boots_and_speed_extend_range_at_the_same_whole_energy_price(self):
        match=self.match(players=1,full_energy_moves=1,start_energy=2)
        p=match.players[0]
        p.equipment.add('Boots')
        p.items['Speed Potion']=1
        self.assertFalse(play(match,'Move',destination=[3,2])['accepted'])
        start=play(match,'Move',destination=[2,2])['event']
        self.assertEqual((start['move_steps'],p.energy),(4,1))
        self.assertTrue(play(match,'Use',item='Speed Potion')['accepted'])
        result=play(match,'Move',destination=[5,6])
        self.assertTrue(result['accepted'])
        self.assertGreater(result['event']['move_steps'],4)
        self.assertEqual(p.energy,0)
        self.assertNotIn('Haste Potion',p.potions)

    def test_shared_farm_use_resets_each_round_and_rejection_preserves_state(self):
        match=self.match(players=2,full_energy_moves=1,start_energy=6, farm_shared_limit=1)
        farm=list(match.board.farms[0])
        match.decks[1]=[('Nothing','Nothing',None)]*6
        for destination in ([0,2],farm):
            self.assertTrue(play(match,'Move',destination=destination)['accepted'])
        self.assertTrue(play(match,'Mine')['accepted'])
        self.assertTrue(play(match,'Move',destination=[1,3])['accepted'])
        self.assertTrue(play(match,'EndTurn')['accepted'])
        for destination in ([0,2],farm):
            self.assertTrue(play(match,'Move',destination=destination)['accepted'])
        self.assertEqual(match.observation(1)['farm_uses_this_round'],
                         [dict(position=tuple(farm),uses=1)])
        prior=(match.revision,match.players[1].energy,match.decks[1].copy())
        self.assertFalse(play(match,'Mine')['accepted'])
        self.assertEqual((match.revision,match.players[1].energy,match.decks[1]),prior)
        self.assertTrue(play(match,'EndTurn')['accepted'])
        self.assertEqual(match.farm_uses,{})
        self.assertTrue(play(match,'EndTurn')['accepted'])
        self.assertTrue(play(match,'Mine')['accepted'])

    def test_search_gear_and_tonic_options_affect_actions(self):
        match=self.match(players=1,full_energy_moves=1,start_energy=4,
                         boots_move_range=3,deep_tonic_energy=2,shield_block_per_level=2)
        player=match.players[0]
        player.equipment.add('Boots')
        self.assertFalse(play(match,'Move',destination=[1,3])['accepted'])
        self.assertTrue(play(match,'Move',destination=[0,3])['accepted'])
        player.potions['Energy Tonic']=1
        self.assertEqual(play(match,'Tonic')['event']['bonus'],2)
        player.shield=1
        exchanges,lost=fight(player,match.settings,Rolls(1,6),3,5)
        self.assertFalse(lost)
        self.assertEqual((exchanges[0]['shield_absorbed'],exchanges[0]['hit']),(2,1))

    def test_seeded_values_and_exact_cost_mining_in_every_zone(self):
        match=self.match(players=1)
        self.assertEqual(decks(match.settings),match.decks)
        for zone,pile in match.decks.items():
            self.assertEqual(len(pile),50)
            for kind,_,value in pile:
                if kind in ('Treasure','Monster'):
                    key='hp' if kind=='Monster' else 'treasure'
                    self.assertLessEqual(getattr(match.settings,f'{key}_min{zone}'),value)
                    self.assertLessEqual(value,getattr(match.settings,f'{key}_max{zone}'))
            p=match.players[0]
            p.position=match.board.farms[zone-1]
            match.decks[zone]=[('Treasure','Jade',2),('Treasure','Opal',4)]
            p.energy=1
            self.assertFalse(play(match,'Mine')['accepted'])
            self.assertEqual((p.energy,len(match.decks[zone])),(1,2))
            p.energy=2
            row=play(match,'Mine')['event']
            self.assertEqual((p.energy,row['draw_count'],row['loot_change']),(0,2,6))
            self.assertFalse(play(match,'Mine')['accepted'])
        p.position=(0,2)
        p.energy=1
        match.decks[1]=[('Treasure','Jade',2),('Treasure','Opal',4)]
        row=play(match,'Mine')['event']
        self.assertEqual((p.energy,row['action_cost'],row['draw_count']),(0,1,1))

    def test_dice_deck_counts_and_invalid_mix(self):
        match=self.match(players=1,deck_monsters2=8,deck_treasures2=25,
                         treasure_min2=7,treasure_max2=7)
        self.assertEqual(Counter(kind for kind,_,_ in match.decks[2]),
                         dict(Monster=8,Treasure=25,Nothing=7,Item=10))
        self.assertTrue(all(value==7 for kind,_,value in match.decks[2] if kind=='Treasure'))
        self.assertEqual(AgentMatch.restore(match.serialize()).decks,match.decks)
        with self.assertRaisesRegex(ValueError,'leave room for 10 Item'):
            self.match(players=1,deck_monsters2=16,deck_treasures2=25)

    def test_starting_energy_and_refill_are_independent_and_replay(self):
        match=self.match(players=2,start_energy=4,gain=1,cap=5)
        p,other=match.players
        self.assertEqual((p.energy,other.energy),(4,4))
        play(match,'Move',destination=[0,1])
        play(match,'EndTurn')
        self.assertEqual((p.energy,other.energy),(3.5,4))
        play(match,'EndTurn')
        self.assertEqual((p.energy,other.energy),(4.5,5))
        play(match,'EndTurn')
        play(match,'EndTurn')
        self.assertEqual((p.energy,other.energy),(5,5))
        self.assertEqual(AgentMatch.restore(match.serialize()).observation(0),match.observation(0))

    def test_version_one_keeps_its_original_opening_pool_and_farm_price(self):
        old_counts={f'deck_{field}{zone}':counts[kind] for zone,counts in COMPOSITION.items()
                    for field,kind in (('monsters','Monster'),('treasures','Treasure'))}
        match=self.match(players=1,gain=5,start_energy=5,mine_cost=3,farm_cost=3,**old_counts)
        for y in (1,2,3):
            self.assertTrue(play(match,'Move',destination=[0,y])['accepted'])
        self.assertTrue(play(match,'Mine')['accepted'])
        saved=match.serialize()
        saved['version']=1
        del saved['settings']['start_energy']
        for field in old_counts:
            del saved['settings'][field]
        saved['settings']['farm_cost']=2  # Version 1 ignored this setting in dice mode.
        restored=AgentMatch.restore(saved)
        self.assertEqual(deck_composition(restored.settings),COMPOSITION)
        self.assertEqual(restored.observation(0),match.observation(0))

    def test_through_occupied_tile_requires_affordable_exit_and_no_end_turn(self):
        match=self.match(players=2)
        p,other=match.players
        other.position=(0,1)
        p.energy=.5
        self.assertFalse(play(match,'Move',destination=[0,1])['accepted'])
        p.energy=1
        self.assertTrue(play(match,'Move',destination=[0,1])['accepted'])
        self.assertFalse(play(match,'EndTurn')['accepted'])
        self.assertTrue(play(match,'Move',destination=[0,2])['accepted'])
        self.assertTrue(play(match,'EndTurn')['accepted'])

    def test_rock_clear_replays_from_original_board(self):
        match=AgentMatch(dict(dice_rules=1,players=1,boss_enabled=0,start_energy=1),
                         dict(rows=['S.....','.#....','.M....','F.....','......',
                                    '.....M','.....F','......','......','.....F'],
                              gates=[0,5,0]))
        self.assertTrue(play(match,'Move',destination=[0,1])['accepted'])
        self.assertFalse(play(match,'Mine',destination=[1,1])['accepted'])
        play(match,'EndTurn')
        self.assertTrue(play(match,'Mine',destination=[1,1])['accepted'])
        saved=json.loads(json.dumps(match.serialize()))
        self.assertEqual(saved['board']['rows'][1][1],'#')
        restored=AgentMatch.restore(saved)
        self.assertEqual(restored.board,match.board)
        self.assertEqual(restored.observation(0),match.observation(0))

    def test_combat_weapon_shield_and_killing_blow(self):
        s=settings_from(dict(dice_rules=1))
        p=Player(energy=4,sword=1,shield=1)
        steps,defeated=fight(p,s,Rolls(1,3),2,6)
        self.assertFalse(defeated)
        self.assertEqual([(step['damage'],step['hit'],step['shield_absorbed']) for step in steps],
                         [(2,1,1),(4,0,0)])
        self.assertEqual(p.energy,3)

    def test_field_starters_and_sword_bonus_are_explicit_dice_settings(self):
        match=self.match(players=1,field_starter_gear=1,sword_damage_bonus=1,
                         sword_price=1,shield_price=1)
        p=match.players[0]
        p.position=(0,6)
        p.treasures=[2,3,4,5]
        p.loot=14
        self.assertFalse(play(match,'Buy',item='Boots')['accepted'])
        self.assertTrue(play(match,'Buy',item='Sword')['accepted'])
        self.assertTrue(play(match,'Buy',item='Shield')['accepted'])
        self.assertEqual((p.sword,p.shield,p.treasures),(1,1,[4,5]))
        exchanges,defeated=fight(p,match.settings,Rolls(1),2,3)
        self.assertFalse(defeated)
        self.assertEqual((exchanges[0]['weapon'],exchanges[0]['damage'],exchanges[0]['hit']),(2,3,0))
        self.assertTrue(play(match,'Buy',item='Sword')['accepted'])
        self.assertEqual((p.sword,p.treasures),(2,[]))

        legacy=self.match(players=1)
        player=legacy.players[0]
        player.position=(0,6)
        player.treasures=[2,3]
        player.loot=5
        self.assertFalse(play(legacy,'Buy',item='Sword')['accepted'])
        self.assertEqual(player.treasures,[2,3])

    def test_exact_zero_hit_loses_all_carried_and_leaves_next_card(self):
        match=self.match(players=2,lose_depth=2)
        p=match.players[0]
        p.position=match.board.farms[2]
        p.energy=5
        p.treasures=[4,5]
        p.loot=9
        p.bank_cards=[7]
        p.bank=7
        match.combat_rngs[0]=Rolls(1)
        match.decks[3]=[('Monster','Spider',9),('Treasure','Opal',4)]
        row=play(match,'Mine')['event']
        self.assertEqual((row['knockdown'],row['loot_penalty'],row['draw_count']),('Yes',9,1))
        self.assertEqual((p.energy,p.loot,p.bank,p.treasures),(0,0,7,[]))
        self.assertEqual(p.position,match.board.exit(1))
        self.assertEqual(match.decks[3],[('Treasure','Opal',4)])
        self.assertEqual(match.active,1)

    def test_gold_shop_one_card_covers_cost_and_keeps_change(self):
        match=self.match(players=1,shop_gold_prices=1,boots_price=2,
                         field_starter_gear=1,sword_price=1)
        p=match.players[0]
        p.bank_cards=[4]
        p.bank=4
        boots=play(match,'Buy',item='Boots')
        self.assertTrue(boots['accepted'])
        self.assertEqual((p.bank,p.bank_cards,boots['event']['bank_spent']),(2,[2],2))
        self.assertIn('2 gold spent',boots['event']['card'])
        p.position=(0,6)
        p.treasures=[0,4]
        p.loot=4
        sword=play(match,'Buy',item='Sword')
        self.assertTrue(sword['accepted'])
        self.assertEqual((p.loot,sorted(p.treasures),p.bank),(3,[0,3],2))
        p.treasures=[1]
        p.loot=1
        upgrade=play(match,'Buy',item='Sword')
        self.assertTrue(upgrade['accepted'])
        self.assertEqual((p.loot,p.treasures,p.bank,p.bank_cards,p.sword),(0,[],1,[1],2))
        self.assertFalse(play(match,'Buy',item='Shield')['accepted'])
        self.assertEqual((p.bank,p.bank_cards),(1,[1]))
        p.items['Coupon']=1
        shield=play(match,'Buy',item='Shield')
        self.assertTrue(shield['accepted'])
        self.assertEqual((p.shield,p.bank,p.bank_cards),(1,0,[]))

    def test_bounty_can_be_banked_and_spent_without_exiting(self):
        match=self.match(players=1)
        p=match.players[0]
        p.position=match.board.farms[0]
        p.energy=7
        match.combat_rngs[0]=Rolls(6)
        match.decks[1]=[('Monster','Spider',4),('Treasure','Opal',4)]
        row=play(match,'Mine')['event']
        self.assertEqual(row['combat_events'][0]['bounty'],1)
        for y in (2,1,0):
            self.assertTrue(play(match,'Move',destination=[0,y])['accepted'])
        self.assertEqual((p.bank,p.bank_cards,p.escaped),(5,[1,4],False))
        p.items['Coupon']=1
        row=play(match,'Buy',item='Sword')['event']
        self.assertEqual((row['bank_spent'],p.bank,p.sword),(1,4,1))
        self.assertFalse(play(match,'Buy',item='Sword')['accepted'])
        self.assertTrue(play(match,'Move',destination=[0,1])['accepted'])
        p.position=next(tile for tile in match.board.shops if tile[1]==6)
        p.treasures=[3]
        p.loot=3
        row=play(match,'Buy',item='Sword')['event']
        self.assertEqual((row['loot_spent'],p.bank,p.sword),(3,4,2))
        self.assertFalse(play(match,'Buy',item='Sword')['accepted'])

    def test_only_surface_players_can_win_and_private_card_values_stay_private(self):
        match=self.match(players=2,turns=3,retreat_start=3)
        best,other=match.players
        best.position=(0,1)
        best.bank=50
        best.bank_cards=[50]
        other.bank=2
        other.bank_cards=[2]
        self.assertNotIn('bank_cards',match.observation(1)['players'][0])
        while not match.complete:
            play(match,'EndTurn')
        self.assertEqual(match.observation(1)['winners'],[1])

    def test_dice_experiment_replays_and_old_shared_mode_is_unchanged(self):
        s=settings_from(dict(dice_rules=1,runs=1,players=3))
        result=experiment(s)
        self.assertEqual(result,experiment(s))
        self.assertIn('hp_min',result['combat'][0])
        old=AgentMatch(dict(shared_decks=1,players=1))
        saved=old.serialize()
        del saved['settings']['dice_rules']
        restored=AgentMatch.restore(saved)
        self.assertFalse(restored.settings.dice_rules)
        self.assertEqual(restored.observation(0),old.observation(0))
