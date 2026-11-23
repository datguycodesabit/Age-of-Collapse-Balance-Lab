import copy
import random
import unittest
from dataclasses import replace
from engine import experiment
from model import (Settings, Board, Player, FARMS, GATES, GEAR, neighbors, path_between, distance_home,
                   movement_cost, perform, buy, run_player, boss_timeline, boss_effect, zone_at,
                   drink_tonic)


class FixedDice:
    def __init__(self,dice): self.dice=iter(dice)
    def randint(self,low,high): return next(self.dice)


class CaveMechanicsTests(unittest.TestCase):
    def quiet(self,**values):
        return replace(Settings(),p_treasure=100,p_monster=0,p_enhance=0,**values)

    def test_energy_drives_many_steps_in_one_turn(self):
        s=self.quiet(turns=2,zone2_start=1,zone3_start=1,retreat_start=3,
                     farm_visits=0,gain=30,cap=30,boss_enabled=0,
                     boots_price=0,flashlight_price=0,climbing_price=0)
        p=run_player(s,random.Random(1))
        moves=[r for r in p['rows'] if r['turn']==1 and r['action']=='Delve']
        self.assertGreater(len(moves),20)
        self.assertEqual(sum(r['gain'] for r in p['rows'] if r['turn']==1),30)

    def test_chokepoints_are_bidirectional_and_all_other_crossings_blocked(self):
        for boundary,row in enumerate(GATES):
            for column in range(6):
                gates=list(GATES.values())
                gates[boundary]=column
                board=Board(gates=tuple(gates))
                for x in range(6):
                    self.assertEqual((x,row) in neighbors((x,row-1),board=board),x==column)
                    self.assertEqual((x,row-1) in neighbors((x,row),board=board),x==column)

    def test_farms_are_opposite_exit_or_deep_entry(self):
        self.assertEqual([FARMS[z][0] for z in (1,2,3)],[0,5,5])
        self.assertEqual(distance_home(FARMS[3]),24)

    def test_flashlight_removes_darkness_both_directions(self):
        s=Settings()
        self.assertEqual(movement_cost((5,3),(5,4),s,set()),3)
        self.assertEqual(movement_cost((5,4),(5,3),s,{'Flashlight'},True),1)
        self.assertEqual(movement_cost((5,4),(5,3),s,set(),True),3)

    def test_kit_and_boots_stack_but_do_not_discount_farming(self):
        s=Settings()
        self.assertEqual(movement_cost((0,7),(1,7),s,set()),6)
        self.assertEqual(movement_cost((0,7),(1,7),s,{'Flashlight','Climbing Kit','Boots'}),.5)
        p=Player(position=FARMS[2],energy=4,equipment={'Boots'})
        r=perform(p,self.quiet(),random.Random(1),'Farm')
        self.assertEqual(r['action_cost'],2)

    def test_two_steps_for_one_energy_with_boots(self):
        p=Player(position=(0,1),energy=1,equipment={'Boots'},visited={(0,1),(0,2),(0,3)})
        s=self.quiet()
        self.assertIsNotNone(perform(p,s,random.Random(1),'Delve',(0,2)))
        self.assertEqual(p.energy,.5)
        self.assertIsNotNone(perform(p,s,random.Random(1),'Delve',(0,3)))
        self.assertEqual(p.energy,0)

    def test_farm_draws_twice_once_per_turn_without_reentry(self):
        p=Player(position=FARMS[1],energy=6,visited={FARMS[1]})
        rng=random.Random(1)
        for _ in range(3):
            row=perform(p,self.quiet(),rng,'Farm')
            self.assertEqual(row['draw_count'],2)
            self.assertEqual(row['position_in'],row['position_out'])
            state=copy.deepcopy(p)
            seed=rng.getstate()
            self.assertIsNone(perform(p,self.quiet(),rng,'Farm'))
            self.assertEqual(p,state)
            self.assertEqual(rng.getstate(),seed)
            p.mined_this_turn.clear()
        self.assertEqual(p.loot,12)
        self.assertEqual(p.energy,0)
        self.assertEqual(len(p.visited),1)

    def test_rejected_actions_preserve_state_and_randomness(self):
        for action,destination in [('Farm',None),('Delve',(5,4)),('Retreat',(0,0))]:
            p=Player(position=(4,3),energy=1);rng=random.Random(1)
            start=copy.deepcopy(p);state=rng.getstate()
            self.assertIsNone(perform(p,Settings(),rng,action,destination))
            self.assertEqual(p,start);self.assertEqual(rng.getstate(),state)
        p=Player(position=FARMS[1],energy=1);rng=random.Random(2);state=rng.getstate()
        self.assertIsNone(perform(p,Settings(),rng,'Farm'))
        self.assertEqual(rng.getstate(),state);self.assertEqual(p.energy,1)

    def test_shop_purchase_is_affordable_local_and_unique(self):
        p=Player(position=(5,3),loot=6)
        self.assertIsNotNone(buy(p,'Flashlight',Settings()))
        self.assertEqual(p.loot,3);self.assertIn('Flashlight',p.equipment)
        before=copy.deepcopy(p)
        self.assertIsNone(buy(p,'Flashlight',Settings()));self.assertEqual(p,before)
        self.assertIsNone(buy(p,'Climbing Kit',Settings()));self.assertEqual(p,before)
        p.position=(4,3);before=copy.deepcopy(p)
        self.assertIsNone(buy(p,'Boots',Settings()));self.assertEqual(p,before)

    def test_disabled_buying_never_spends_loot(self):
        p=Player(position=(5,3),loot=100)
        self.assertIsNone(buy(p,'Boots',replace(Settings(),buy_boots=0)))
        self.assertEqual(p.loot,100)

    def test_gear_catalog_and_slot_limit(self):
        self.assertEqual(len(GEAR),10)
        player=Player(loot=50)
        settings=replace(Settings(),gear_slots=1)
        self.assertIsNotNone(buy(player,'Mining Pick',settings))
        self.assertIsNone(buy(player,'Boots',settings))
        self.assertEqual(player.loot,45)

    def test_farming_gear_and_fortune_charge(self):
        player=Player(position=FARMS[1],energy=2,equipment={'Mining Pick','Prospector Charm'},
                      potions={'Fortune Potion':1})
        result=perform(player,self.quiet(),random.Random(1),'Farm')
        self.assertEqual(result['action_cost'],1)
        self.assertEqual(result['loot_change'],9)
        self.assertEqual(result['potions_used'],['Fortune Potion'])
        player.mined_this_turn.clear()
        self.assertEqual(perform(player,self.quiet(),random.Random(1),'Farm')['loot_change'],6)

    def test_regular_mine_draws_once_and_does_not_block_other_sites(self):
        player=Player(position=(0,1),energy=10,equipment={'Mining Pick'},potion_rng=random.Random(1))
        settings=self.quiet(potion_chance=100)
        rng=random.Random(7)
        arrival=perform(player,settings,rng,'Delve',(0,2))
        self.assertEqual(arrival['draw_count'],1)
        mine=perform(player,settings,rng,'Mine')
        self.assertEqual((mine['draw_count'],mine['action_cost'],len(mine['potions_found'])),(1,1,1))
        self.assertIn('Mining Pick',player.gear_used)
        self.assertIsNone(perform(player,settings,rng,'Mine'))
        self.assertIsNone(perform(player,settings,rng,'Farm'))
        perform(player,settings,rng,'Delve',FARMS[1])
        self.assertEqual(perform(player,settings,rng,'Farm')['draw_count'],2)

    def test_mining_turn_limit_resets_during_expedition(self):
        settings=self.quiet(turns=4,zone2_start=5,zone3_start=5,retreat_start=5,
                            potion_chance=0,gain=15,cap=15,boss_enabled=0)
        result=run_player(settings,random.Random(3))
        paid=[row for row in result['rows'] if row['action'] in ('Mine','Farm')]
        keys=[(row['turn'],row['position_in']) for row in paid]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertGreater(len(keys),len({tile for _,tile in keys}))
        self.assertGreater(len(keys),len({turn for turn,_ in keys}))

    def test_tuned_gear_effects_change_cost_and_usage(self):
        settings=replace(Settings(),p_treasure=0,p_monster=100,p_enhance=0,blade_savings=3)
        baseline=Player(position=FARMS[1],energy=20)
        equipped=Player(position=FARMS[1],energy=20,equipment={'Cave Blade'})
        cost=perform(baseline,settings,random.Random(3),'Farm')['combat_cost']
        reduced=perform(equipped,settings,random.Random(3),'Farm')['combat_cost']
        self.assertEqual(cost-reduced,6)
        self.assertIn('Cave Blade',equipped.gear_used)
        disabled=Player(position=FARMS[1],energy=20,equipment={'Cave Blade'})
        row=perform(disabled,replace(settings,blade_savings=0),random.Random(3),'Farm')
        self.assertEqual(row['combat_cost'],cost)
        self.assertNotIn('Cave Blade',disabled.gear_used)

    def test_single_use_glow_and_rejected_move(self):
        player=Player(position=(5,3),energy=1,potions={'Glow Potion':1})
        settings=Settings()
        rng=random.Random(1)
        self.assertIsNone(perform(player,settings,rng,'Delve',(4,4)))
        self.assertEqual(player.potions,{'Glow Potion':1})
        row=perform(player,settings,rng,'Retreat',(5,4))
        self.assertEqual(row['action_cost'],1)
        self.assertEqual(row['potions_used'],['Glow Potion'])
        self.assertEqual(player.potions,{})

    def test_haste_lasts_one_step_and_tonic_respects_cap(self):
        player=Player(position=(0,1),energy=.5,potions={'Haste Potion':1,'Energy Tonic':1})
        settings=replace(Settings(),cap=2)
        row=perform(player,settings,random.Random(1),'Retreat',(0,0))
        self.assertEqual(row['action_cost'],.5)
        self.assertEqual(row['potions_used'],['Haste Potion'])
        self.assertIsNone(perform(player,settings,random.Random(1),'Delve',(0,1)))
        self.assertEqual(drink_tonic(player,settings,())['bonus'],2)
        self.assertIsNone(drink_tonic(player,settings,()))

    def test_blade_and_ward_save_an_unaffordable_monster(self):
        player=Player(position=FARMS[1],energy=4,equipment={'Cave Blade'},potions={'Ward Potion':1})
        settings=replace(Settings(),p_treasure=0,p_monster=100,p_enhance=0)
        # Two monsters cost 4 each. Blade removes 4 total, then Ward removes 4.
        row=perform(player,settings,random.Random(1),'Farm')
        self.assertEqual(row['potions_used'],['Ward Potion'])
        self.assertEqual(row['combat_cost'],0)
        self.assertEqual(row['knockdown'],'No')

    def test_pack_and_harness_protect_against_different_losses(self):
        player=Player(position=FARMS[1],loot=8,energy=2,equipment={'Padded Pack'})
        settings=replace(Settings(),p_treasure=0,p_monster=100,p_enhance=0)
        self.assertEqual(perform(player,settings,random.Random(1),'Farm')['loot_penalty'],0)
        player.position=(5,9);player.energy=5;player.equipment={'Safety Harness'}
        event=dict(collapse=3,closed=[3],die=6,threatened=3,active_zone=2)
        row=boss_effect(player,event,settings)
        self.assertEqual((row['loot_penalty'],row['action_cost']),(0,1))

    def test_battery_and_map_affect_later_turns_and_retreat(self):
        settings=self.quiet(gear_priority=3,gear_slots=2,map_price=0,battery_price=0,
                            buy_boots=0,buy_harness=0,buy_pack=0)
        player=run_player(settings,random.Random(1))
        self.assertIn('Spare Battery',player['equipment'])
        self.assertEqual(player['rows'][0]['gain'],settings.gain)
        self.assertTrue(any(row['gain']==settings.gain+1 for row in player['rows']))
        self.assertEqual(movement_cost((0,1),(0,0),settings,{'Trail Map'},True),.5)

    def test_finds_bonus_potions_per_card_but_cannot_use_them_until_next_action(self):
        player=Player(position=FARMS[1],energy=2,potion_rng=random.Random(3))
        row=perform(player,self.quiet(potion_chance=100),random.Random(1),'Farm')
        self.assertEqual(row['cards'],['Treasure','Treasure'])
        self.assertEqual(len(row['potions_found']),2)
        self.assertEqual(row['potions_used'],[])
        self.assertEqual(sum(player.potions.values()),2)

    def test_shopping_priorities_and_depth_change_actual_runs(self):
        settings=self.quiet(runs=2,players=1,gear_slots=1,retreat_start=11,potion_chance=0)
        farmer=experiment(replace(settings,gear_priority=1,max_zone=1))
        delver=experiment(replace(settings,gear_priority=2))
        self.assertEqual(farmer['metrics']['zone3_rate'],0)
        self.assertEqual(farmer['players'][0]['equipment'],['Mining Pick'])
        self.assertEqual(delver['players'][0]['equipment'],['Flashlight'])

    def test_deep_cache_pays_on_first_arrival_and_cannot_be_farmed(self):
        setup=self.quiet(deep_cache_loot=6,potion_chance=0)
        approach=(4,9)
        player=Player(position=approach,energy=20,equipment={'Flashlight','Climbing Kit'})
        rng=random.Random(3)
        first=perform(player,setup,rng,'Delve',FARMS[3])
        self.assertEqual((first['cache_loot'],first['loot_change'],first['draw_count']),(6,12,1))
        self.assertEqual(player.bank,0)
        farm=perform(player,setup,rng,'Farm')
        self.assertEqual((farm['cache_loot'],farm['loot_change'],farm['draw_count']),(0,12,2))
        perform(player,setup,rng,'Retreat',approach)
        again=perform(player,setup,rng,'Delve',FARMS[3])
        self.assertEqual((again['cache_loot'],again['loot_change'],again['draw_count']),(0,0,0))

    def test_zone_3_monster_is_survivable_with_a_combat_reserve(self):
        settings=replace(Settings(),p_treasure=0,p_monster=100,p_enhance=0,potion_chance=0)
        for gear,cost in ((set(),9),({'Cave Blade'},7)):
            player=Player(position=(4,9),energy=10,equipment=gear|{'Flashlight','Climbing Kit'})
            event=perform(player,settings,random.Random(3),'Delve',FARMS[3])
            self.assertEqual((event['monster_attack'],event['combat_cost'],event['knockdown']),(3,cost,'No'))
            self.assertEqual(player.energy,9-cost)

    def test_gate_tonic_is_a_one_time_find_at_the_configured_entrance(self):
        board=Board(gates=(0,5,2))
        settings=replace(Settings(),p_treasure=0,p_monster=0,p_enhance=0,potion_chance=0)
        gear={'Boots','Flashlight','Cave Blade'}
        player=Player(board=board,position=(2,6),energy=7,equipment=gear.copy(),
                      potion_rng=random.Random(1))
        rng=random.Random(3)
        potion_state=player.potion_rng.getstate()
        self.assertIsNone(perform(player,settings,rng,'Delve',(2,7),closed=(3,)))
        self.assertEqual(player.potions,{})
        first=perform(player,settings,rng,'Delve',(2,7))
        self.assertEqual((first['cards'],first['empty_draws']),(['Nothing'],0))
        self.assertTrue(first['gate_tonic'])
        self.assertEqual(first['potions_found'],['Energy Tonic'])
        self.assertEqual(player.potion_rng.getstate(),potion_state)
        self.assertEqual(player.equipment,gear)
        drank=drink_tonic(player,settings,())
        self.assertEqual((drank['bonus'],player.energy),(3,9))
        self.assertIsNone(drink_tonic(player,settings,()))
        self.assertIsNotNone(perform(player,settings,rng,'Retreat',(2,6)))
        again=perform(player,settings,rng,'Delve',(2,7))
        self.assertFalse(again['gate_tonic'])
        self.assertEqual(again['potions_found'],[])

        other=Player(board=board,position=(2,6),energy=7,equipment=gear.copy())
        first=perform(other,settings,rng,'Delve',(2,7))
        self.assertTrue(first['gate_tonic'])
        disabled=Player(board=board,position=(2,6),energy=7,equipment=gear.copy())
        first=perform(disabled,replace(settings,deep_entry_tonic=0),rng,'Delve',(2,7))
        self.assertFalse(first['gate_tonic'])
        self.assertEqual((first['potions_found'],first['empty_draws']),([],1))

    def test_owned_gear_only_counts_when_its_effect_changes_an_action(self):
        player=Player(position=(0,2),energy=5,equipment={'Flashlight','Boots','Trail Map'})
        row=perform(player,Settings(),random.Random(1),'Retreat',(0,1))
        self.assertEqual(row['action_cost'],.25)
        self.assertEqual(player.gear_used,{'Boots','Trail Map'})

    def test_harness_prevents_monster_pushback(self):
        player=Player(position=FARMS[1],energy=2,equipment={'Safety Harness'})
        settings=replace(Settings(),p_treasure=0,p_monster=100,p_enhance=0)
        row=perform(player,settings,random.Random(1),'Farm')
        self.assertEqual(row['knockdown'],'Yes')
        self.assertEqual(player.position,FARMS[1])
        self.assertEqual(player.gear_used,{'Safety Harness'})

    def test_mixed_shoppers_use_price_and_produce_reproducible_rates(self):
        settings=self.quiet(gear_priority=4,runs=12,players=4)
        result=experiment(settings)
        self.assertEqual(result,experiment(settings))
        for rate in result['equipment_rates']:
            self.assertLessEqual(rate['used'],rate['count'])
        high_price=experiment(replace(settings,boots_price=100))
        boots=lambda report: next(r for r in report['equipment_rates'] if r['label']=='Boots')
        self.assertLess(boots(high_price)['count'],boots(result)['count'])

    def test_dark_gate_rejects_unaffordable_step_before_draw(self):
        p=Player(position=(5,3),energy=2);rng=random.Random(1)
        start=copy.deepcopy(p);state=rng.getstate()
        self.assertIsNone(perform(p,Settings(),rng,'Delve',(5,4)))
        self.assertEqual(p,start);self.assertEqual(rng.getstate(),state)

    def test_discovery_stays_once_per_tile(self):
        p=Player(position=(0,1),energy=10)
        s=self.quiet();rng=random.Random(1)
        a=perform(p,s,rng,'Delve',(0,2));perform(p,s,rng,'Delve',(0,1))
        b=perform(p,s,rng,'Delve',(0,2))
        self.assertEqual(a['draw_count'],1);self.assertEqual(b['draw_count'],0)

    def test_boss_arrival_and_dice_hold_or_advance_one_zone(self):
        events=boss_timeline(Settings(),FixedDice([2,6,4,1]))
        self.assertTrue(all(e['die']==0 for e in events[:11]))
        self.assertEqual(events[11]['closed'],[])
        self.assertEqual(events[12]['closed'],[3])
        self.assertEqual(events[13]['closed'],[2,3])
        self.assertEqual(events[14]['closed'],[2,3])

    def test_boss_ejection_closes_area_and_spends_penalty_once(self):
        p=Player(position=(5,9),energy=5,loot=10,visited={(5,9)})
        s=Settings();event=boss_timeline(replace(s,boss_start=1),FixedDice([6,6,6]))[0]
        row=boss_effect(p,event,s)
        self.assertEqual(p.position,(0,6));self.assertEqual(p.loot,8);self.assertEqual(p.energy,3)
        self.assertTrue(row['boss_ejection']);self.assertEqual(row['collapsed'],[3])
        self.assertEqual(path_between((0,6),(0,7),(3,)),())
        state=copy.deepcopy(p);rng=random.Random(1);random_state=rng.getstate()
        self.assertIsNone(perform(p,s,rng,'Delve',(0,7),(3,)))
        self.assertEqual(p,state);self.assertEqual(rng.getstate(),random_state)

    def test_final_seal_kills_underground_players_and_preserves_surface_players(self):
        event=dict(collapse=1,closed=[1,2,3],die=6,threatened=1,active_zone=0)
        for position in ((4,2),(0,6),(5,9)):
            p=Player(position=position,energy=2,loot=8,visited={position},equipment={'Safety Harness'})
            row=boss_effect(p,event,Settings())
            self.assertTrue(p.killed)
            self.assertFalse(p.escaped)
            self.assertEqual((p.bank,p.loot),(0,0))
            self.assertEqual(row['loot_penalty'],8)
            self.assertEqual(row['action'],'Killed by boss')
        p=Player(position=(0,0),loot=8,visited={(0,1)})
        row=boss_effect(p,event,Settings())
        self.assertFalse(p.killed)
        self.assertEqual(p.loot,8)
        self.assertEqual(row['action'],'Boss seals entrance')

    def test_full_collapse_stops_dice_and_entry(self):
        events=boss_timeline(replace(Settings(),boss_start=1,boss_threshold=1),FixedDice([1,1,1]))
        self.assertEqual(events[2]['closed'],[1,2,3])
        self.assertTrue(all(e['die']==0 for e in events[3:]))
        self.assertNotIn((0,1),neighbors((0,0),(1,2,3)))

    def test_players_share_boss_rolls_within_game(self):
        r=experiment(replace(Settings(),runs=2,players=2),4)
        a,b,c=r['samples'][:3]
        self.assertEqual(a['boss_timeline'],b['boss_timeline'])
        self.assertNotEqual(a['boss_timeline'],c['boss_timeline'])

    def test_shared_boss_does_not_claim_independent_player_intervals(self):
        m=experiment(replace(Settings(),runs=1,players=2),0)['metrics']
        self.assertEqual(m['ci_method'],'Game-cluster approximation')
        self.assertEqual(m['score_ci'],[None,None])
        self.assertEqual(m['escape_ci'],[0,100])

    def test_final_turn_walkout_precedes_boss_roll(self):
        s=self.quiet(turns=2,zone2_start=3,zone3_start=3,retreat_start=2,farm_visits=0,
                     buy_boots=0,buy_flashlight=0,buy_climbing=0)
        schedule=[dict(turn=1,die=0,threatened=0,collapse=0,active_zone=0,closed=[2,3]),
                  dict(turn=2,die=6,threatened=1,collapse=1,active_zone=0,closed=[1,2,3])]
        p=run_player(s,random.Random(1),schedule)
        self.assertEqual(p['escaped'],1);self.assertEqual(p['killed'],0)
        self.assertEqual(p['rows'][-1]['action'],'Extract')
        self.assertEqual(p['boss_ejections'],0)

    def test_energy_and_loot_reconcile_over_random_runs(self):
        s=Settings()
        for seed in range(30):
            p=run_player(s,random.Random(seed));rows=p['rows']
            self.assertEqual(sum(r['loot_change'] for r in rows),p['score']+p['carried']+p['equipment_spent']+sum(r['loot_penalty'] for r in rows))
            for r in rows:
                self.assertTrue(0<=r['end_energy']<=s.cap)
                if not r['killed']:
                    self.assertNotIn(zone_at(r['position_out']),r['collapsed'])
                self.assertAlmostEqual(r['raw_energy'],r['available']-r['action_cost']-r['combat_cost']+r['bonus'])

    def test_boss_seal_ends_runs_without_a_winner_when_everyone_dies(self):
        s=self.quiet(runs=1,players=2,boss_start=1,boss_threshold=1,retreat_start=15,
                     cap=3,gain=3,potion_chance=0,gear_slots=0)
        result=experiment(s)
        self.assertEqual(result['metrics']['boss_death_rate'],100)
        self.assertEqual(result['metrics']['no_survivor_game_rate'],100)
        self.assertEqual(result['metrics']['avg_score'],0)
        self.assertEqual(result['diagnostics']['boss_deaths'][1],2)
        self.assertFalse(any(player['winner'] for player in result['players']))
        self.assertTrue(all(p['rows'][-1]['turn']==3 for p in result['samples']))

    def test_enhancement_only_farming_terminates_without_step_cap(self):
        s=replace(Settings(),p_treasure=0,p_monster=0,p_enhance=100,enhance=20,
                  boots_price=0,flashlight_price=0,climbing_price=0)
        p=run_player(s,random.Random(1))
        self.assertLess(len(p['rows']),2000)
        self.assertLessEqual(p['farm_actions'],s.turns*s.farm_visits*3)


if __name__=='__main__':unittest.main()
