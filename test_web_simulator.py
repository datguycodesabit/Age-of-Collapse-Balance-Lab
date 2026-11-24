import http.client
import json
import random
import threading
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from http.server import ThreadingHTTPServer

from engine import board_from, board_metadata, experiment, farm_variants, generated_maps, route_study, search, settings_from, wilson
from ev_audit import audit, options
from model import GEAR, Player, Settings, run_player, zone_at, path_between, distance_home, return_turns_needed
from server import Handler
from settings_presets import CATALOG, variants
from study_design import generated_family
from tune_turn_length import PRESET


class ExperimentTests(unittest.TestCase):
    def test_all_search_presets_generate_distinct_legal_variants(self):
        self.assertEqual(len(CATALOG),20)
        preset=json.loads(PRESET.read_text())
        settings,board=settings_from(preset['settings']),board_from(preset['board'])
        for key in CATALOG:
            with self.subTest(preset=key):
                candidates=variants(key,settings,board)
                self.assertGreaterEqual(len(candidates),2)
                self.assertEqual(candidates[0]['board'],preset['board'])
                self.assertEqual(len(candidates),len({json.dumps(c,sort_keys=True) for c in candidates}))
                for row in candidates:
                    self.assertEqual(board_metadata(board_from(row['board']))['layout'],row['board'])
                    settings_from(dict(asdict(settings),**row['changes']))

    def test_development_metrics_match_the_replayed_dice_actions(self):
        from tune_turn_length import PRESET
        preset=json.loads(PRESET.read_text())
        settings=settings_from({**preset['settings'],'runs':3})
        result=experiment(settings,board=board_from(preset['board']))
        report=result['development']
        samples=result['samples']
        self.assertEqual(sum(report['outcomes'].values()),len(samples))
        self.assertEqual(report['outcomes']['scored'],sum(player['score']>0 for player in samples))
        self.assertEqual(report['first_bank_timeline'][-1],
                         sum(player['first_bank_round'] is not None for player in samples))
        self.assertGreater(report['first_bank_timeline'][-1],0)
        self.assertEqual(report['energy']['walking'],result['metrics']['avg_movement_energy'])
        for zone in report['zones']:
            depth=zone['zone']
            draws=[sum(row['draw_count'] for player in samples if player['game']==game
                       for row in player['rows'] if row['farm_zone']==depth)
                   for game in (1,2,3)]
            self.assertAlmostEqual(zone['draws'],sum(draws)/3)
            self.assertAlmostEqual(zone['left']+zone['draws'],50)
            self.assertEqual(zone['exhausted'],draws.count(50))
            qualified=sum(player['escaped'] and any(
                mine['farm_zone']==depth and mine['draw_count']
                and any(row.get('banked_now',0)>0 for row in player['rows'][i+1:])
                for i,mine in enumerate(player['rows'])) for player in samples)
            self.assertEqual(result['metrics'][f'zone{depth}_bank_rate'],100*qualified/len(samples))
            self.assertEqual(result['metrics'][f'zone{depth}_depletion_rate'],100*draws.count(50)/3)
        for gear in report['gear']:
            self.assertEqual(gear['bought'],sum(any(row['action']=='Buy '+gear['item'] for row in player['rows'])
                                                 for player in samples))
            self.assertLessEqual(gear['used'],gear['bought'])

    def compact_layout(self):
        return dict(gates=[2,2,2],rows=['..S...','......','......','..F...','..S...',
                                        '......','..F...','..S...','......','..F...'])

    def test_map_layout_changes_walk_and_return_distance(self):
        board=board_from(self.compact_layout())
        self.assertEqual(board_metadata()['deepest_return_steps'],24)
        self.assertEqual(board_metadata(board)['deepest_return_steps'],9)
        settings=self.quiet(runs=1,players=1,retreat_start=12,gain=12,cap=12)
        result=experiment(settings,board=board)
        rows=result['samples'][0]['rows']
        self.assertEqual(rows[0]['position_in'],(2,0))
        for row in rows:
            if row['action'] in ('Delve','Retreat'):
                start,end=row['position_in'],row['position_out']
                self.assertEqual(sum(abs(a-b) for a,b in zip(start,end)),1)
                if row['start_depth']!=row['end_depth']:
                    self.assertEqual((start[0],end[0]),(2,2))
        self.assertTrue(any(r['action']=='Farm' and r['position_out']==(2,6) for r in rows))

    def test_generated_layouts_are_distinct_reachable_and_seeded(self):
        original=board_from(self.compact_layout())
        candidates=list(generated_maps(original,87,12))
        self.assertEqual(candidates,list(generated_maps(original,87,12)))
        self.assertEqual(len(set(candidates)),12)
        for board in candidates:
            self.assertEqual(board_from(board_metadata(board)['layout']),board)
            self.assertEqual(len(board.shops),len(original.shops))
            for zone in (1,2,3):
                self.assertEqual(sum(zone_at(tile)==zone for tile in board.mines),2)
                boundary=board.entrance(3) if zone==3 else board.exit(zone)
                self.assertGreaterEqual(abs(board.farms[zone-1][0]-boundary[0]),3)

    def test_farm_free_and_dense_maps_round_trip_and_produce_routes(self):
        blank=dict(gates=[1,4,2],rows=['......']*10)
        farm_free=board_from(blank)
        shape=board_metadata(farm_free)
        self.assertEqual(shape['layout'],dict(blank,shop_detours=False))
        self.assertEqual(shape['farm_distances'],[])
        self.assertIsNone(shape['deepest_return_steps'])
        self.assertIn((2,7),shape['route'])
        dense=board_from(dict(blank,rows=['......']+['FFFFFF']*9))
        self.assertEqual(len(dense.farms),54)
        self.assertEqual(board_from(board_metadata(dense)['layout']),dense)
        self.assertEqual([len(dense.farms_in(z)) for z in (1,2,3)],[18,18,18])
        for board in (farm_free,dense):
            for settings in (self.quiet(runs=1,players=1),
                             settings_from(dict(dice_rules=1,runs=1,players=1))):
                result=experiment(settings,board=board)
                self.assertEqual(result['metrics']['player_runs'],1)
        invalid=dict(blank,rows=['F.....']+['......']*9)
        with self.assertRaisesRegex(ValueError,'farms underground'):
            board_from(invalid)

    def test_generated_families_preserve_mixed_farm_counts_and_moved_gates(self):
        source=board_from(dict(gates=[2,3,4],rows=['......','F.F...','.....F','......',
                                                 '...M..','......','......','......','..F...','......']))
        self.assertEqual([len(source.farms_in(z)) for z in (1,2,3)],[3,0,1])
        for generator in (list(generated_maps(source,42,3)),
                          generated_family(source,42,3,[(1,59)]*3)):
            self.assertEqual(len(generator),3)
            for board in generator:
                self.assertEqual([len(board.farms_in(z)) for z in (1,2,3)],[3,0,1])
                self.assertEqual(board_from(board_metadata(board)['layout']),board)

    def test_map_rejects_blocked_gate_and_disconnected_floor(self):
        layout=self.compact_layout()
        layout['rows'][1]='..#...'
        with self.assertRaisesRegex(ValueError,'gate must be open'): board_from(layout)
        layout=self.compact_layout()
        layout['rows'][2]='######'
        with self.assertRaisesRegex(ValueError,'cut off'): board_from(layout)

    def test_players_walk_to_a_relocated_shop_before_buying(self):
        layout=self.compact_layout()
        layout['shop_detours']=True
        layout['rows'][0]='......'
        layout['rows'][1]='S.....'
        switches={flag:int(item=='Boots') for item,(_,flag) in GEAR.items()}
        settings=replace(self.quiet(runs=1,players=1),gear_slots=1,boots_price=1,
                         **switches)
        rows=experiment(settings,board=board_from(layout))['samples'][0]['rows']
        purchase=next(i for i,row in enumerate(rows) if row['action']=='Buy Boots')
        self.assertEqual(rows[purchase-1]['action'],'Delve')
        self.assertEqual(rows[purchase-1]['position_out'],(0,1))
        self.assertEqual(rows[purchase]['position_in'],(0,1))

    def test_original_layout_round_trips_and_rocks_change_paths(self):
        self.assertEqual(board_metadata(board_from(board_metadata()['layout'])),board_metadata())
        layout=self.compact_layout()
        layout['rows'][2]='..#...'
        board=board_from(layout)
        self.assertEqual(board_metadata(board)['deepest_return_steps'],11)

    def test_farm_trials_move_only_the_selected_farm_by_exact_distances(self):
        board=board_from(self.compact_layout())
        trials=list(farm_variants(board,1))
        self.assertEqual([steps for steps,_ in trials],[2,4,6])
        for steps,layout in trials:
            self.assertEqual(board_metadata(layout)['distances'][0]['farm_detour'],steps)
            self.assertEqual(replace(layout,farms=board.farms),board)
            self.assertEqual(layout.farms[1:],board.farms[1:])
        settings=self.quiet(runs=1,players=1,farm_detour_limit=0,gain=12,cap=12)
        result=experiment(settings,board=trials[-1][1])
        self.assertFalse(any(r['farm_zone']==1 for r in result['samples'][0]['rows']))
        self.assertEqual(result['diagnostics']['gates'][1],1)

    def test_return_estimate_uses_owned_gear_and_adaptive_policy_commits(self):
        board=board_from(self.compact_layout())
        settings=self.quiet(runs=1,players=1,gain=2,cap=10)
        player=Player(board=board,position=(2,6),energy=2)
        self.assertGreater(return_turns_needed(player,settings,()),0)
        original=return_turns_needed(player,settings,())
        player.equipment.update({'Boots','Flashlight'})
        self.assertLess(return_turns_needed(player,settings,()),original)
        changed=replace(settings,adaptive_retreat=1,retreat_slack=1)
        rows=experiment(changed,board=board)['samples'][0]['rows']
        plan=next(i for i,row in enumerate(rows) if row['action']=='Plan retreat')
        self.assertFalse(any(r['action'] in ('Delve','Farm') for r in rows[plan+1:]))
        self.assertEqual(rows[-1]['action'],'Extract')

    def test_equipment_trial_tracks_direct_energy_savings_and_control(self):
        board=board_from(self.compact_layout())
        switches={flag:int(item=='Flashlight') for item,(_,flag) in GEAR.items()}
        settings=replace(self.quiet(players=1,gain=12,cap=12),gear_slots=1,flashlight_price=0,**switches)
        spec=dict(kind='gear',games=2,item='Flashlight')
        rows=route_study(settings,spec,lambda _:None,lambda:False,board)['rows']
        self.assertGreater(rows[0]['gear']['walking_energy_saved'],0)
        self.assertEqual(rows[1]['gear']['walking_energy_saved'],0)
        self.assertEqual(rows[0]['layout'],rows[1]['layout'])
        self.assertEqual(rows[0]['metrics']['player_runs'],2)

    def test_route_diagnostics_reconcile_unextracted_and_gate_counts(self):
        report=experiment(self.quiet(runs=2,players=1,gain=1,cap=1))
        diagnostics=report['diagnostics']
        self.assertEqual(diagnostics['gates'][0],2)
        self.assertEqual(sum(diagnostics['stranded']),2-report['metrics']['escaped'])
        self.assertEqual(sum(diagnostics['waits'].values()),round(report['metrics']['avg_waits']*2))
    def quiet(self,**values):
        return replace(Settings(),p_treasure=100,p_monster=0,p_enhance=0,boss_enabled=0,gear_slots=0,potion_chance=0,**values)

    def test_depth_study_uses_cache_only_in_the_treatment(self):
        settings=self.quiet(players=1,gain=12,cap=12,zone2_start=1,zone3_start=1,
                            deep_cache_loot=6,retreat_start=12)
        board=board_from(self.compact_layout())
        study=route_study(settings,{'kind':'depth','games':2},lambda _:None,lambda:False,board)
        shallow,control,cache=[row['metrics'] for row in study['rows']]
        self.assertEqual(shallow['zone3_rate'],0)
        self.assertEqual(control['cache_claim_rate'],0)
        self.assertEqual(cache['cache_claim_rate'],100)
        self.assertEqual(cache['escape_rate'],control['escape_rate'])
        self.assertGreater(cache['avg_score'],control['avg_score'])

    def test_new_rules_replay_deterministically(self):
        for seed in range(20):
            settings=Settings(seed=seed)
            self.assertEqual(run_player(settings,random.Random(seed)),run_player(settings,random.Random(seed)))

    def test_board_area_and_adjacent_retreat(self):
        counts=[sum(zone_at((x,y))==z for x in range(6) for y in range(10)) for z in range(4)]
        self.assertEqual(counts,[6,18,18,18])
        path=path_between((5,9),(0,0))
        self.assertEqual(len(path)-1,24)
        for a,b in zip(path,path[1:]):
            self.assertEqual(abs(a[0]-b[0])+abs(a[1]-b[1]),1)

    def test_exact_metrics_and_histogram_reconcile(self):
        s=self.quiet(runs=5,players=2,turns=2,zone2_start=3,zone3_start=3,retreat_start=2,farm_visits=0)
        result=experiment(s);m=result['metrics']
        self.assertEqual(m['player_runs'],10)
        self.assertEqual(m['escape_rate'],100)
        self.assertEqual(m['zone3_rate'],0)
        self.assertEqual(m['avg_score'],6)
        self.assertEqual(m['avg_unbanked'],0)
        self.assertEqual(sum(h['count'] for h in result['histogram']),10)
        self.assertEqual(result['timeline'][-1]['extracted_pct'],100)
        self.assertEqual(sum(p['score'] for p in result['players'])/10,m['avg_score'])
        self.assertTrue(all(p['winner'] for p in result['players']))  # Identical extracted scores tie.

    def test_late_retreat_scores_zero_and_unbanked_is_measured(self):
        result=experiment(self.quiet(runs=2,players=1,gain=1,cap=1,farm_visits=0))
        self.assertEqual(result['metrics']['escape_rate'],0)
        self.assertEqual(result['metrics']['avg_score'],0)
        self.assertGreater(result['metrics']['avg_unbanked'],0)
        self.assertTrue(result['advice'])

    def test_reproducible_independent_player_streams(self):
        s=replace(Settings(),runs=5,players=2)
        self.assertEqual(experiment(s),experiment(s))
        direct=run_player(s,random.Random(s.seed+104729),potion_seed=s.seed+104729+535013)
        self.assertEqual(experiment(s)['samples'][1]['rows'],direct['rows'])

    def test_cancel_and_bounds(self):
        with self.assertRaises(InterruptedError):experiment(Settings(),cancel=lambda:True)
        with self.assertRaises(ValueError):experiment(Settings(runs=10000,players=20))
        for value in ({'steps_per_turn':1.5},{'gain':True},{'cap':float('nan')},{'missing':1}):
            with self.assertRaises(ValueError):settings_from(value)

    def test_zero_and_hundred_rate_intervals_are_not_zero_width(self):
        low,high=wilson(0,100)
        self.assertEqual(low,0);self.assertGreater(high,0)
        low,high=wilson(100,100)
        self.assertLess(low,100);self.assertAlmostEqual(high,100)

    def test_target_search_finds_known_reachable_score(self):
        s=self.quiet(turns=2,zone2_start=3,zone3_start=3,retreat_start=2,farm_visits=0)
        spec=dict(metric='avg_score',target=9,tolerance=0,budget=5,trials=50,confirmation=200,
                  ranges={'loot_per_depth':{'min':1,'max':5,'step':1}})
        progress=[];answer=search(s,spec,progress.append)
        self.assertTrue(answer['matched'])
        self.assertEqual(answer['recommendations'][0]['changes'],{'loot_per_depth':3})
        self.assertEqual(answer['recommendations'][0]['validation_value'],9)
        self.assertEqual(answer['searched'],5);self.assertEqual(len(progress),10)
        self.assertNotEqual(answer['settings']['seed'],answer['validation_seed'])

    def test_regular_mines_round_trip_and_old_layouts_stay_exact(self):
        legacy=self.compact_layout()
        self.assertEqual(board_metadata(board_from(legacy))['layout']['rows'],legacy['rows'])
        self.assertFalse(board_from(legacy).mines)
        with_mine={**legacy,'rows':[row if i!=2 else '..M...' for i,row in enumerate(legacy['rows'])]}
        self.assertEqual(board_from(with_mine).mines,frozenset({(2,2)}))
        self.assertEqual(board_metadata(board_from(with_mine))['layout']['rows'],with_mine['rows'])
        with_mine['rows'][0]='M.S...'
        with self.assertRaisesRegex(ValueError,'underground'):
            board_from(with_mine)

    def test_nothing_and_truly_empty_draws_are_counted_separately(self):
        settings=replace(Settings(),runs=1,players=1,p_treasure=0,p_monster=0,p_enhance=0,potion_chance=100)
        metrics=experiment(settings)['metrics']
        self.assertGreater(metrics['card_counts']['Nothing'],0)
        self.assertEqual(sum(metrics['card_counts'].values()),metrics['avg_encounters'])
        self.assertEqual(metrics['empty_draws'],0)
        metrics=experiment(replace(settings,potion_chance=0,deep_entry_tonic=0))['metrics']
        self.assertEqual(metrics['empty_draws'],metrics['card_counts']['Nothing'])

    def test_unreachable_target_is_explicit(self):
        answer=search(self.quiet(),dict(metric='avg_score',target=10000,tolerance=1,budget=5,trials=50,confirmation=200,
                         ranges={'loot_per_depth':{'min':1,'max':3,'step':1}}))
        self.assertFalse(answer['matched']);self.assertEqual(answer['searched'],3)

    def test_search_is_reproducible_and_within_selected_grid(self):
        s=Settings(runs=1)
        spec=dict(metric='escape_rate',target=65,budget=5,trials=50,confirmation=200,
                  ranges={'gain':{'min':2,'max':10,'step':2},'boots_price':{'min':1,'max':3,'step':1}})
        first=search(s,spec);self.assertEqual(first,search(s,spec))
        self.assertEqual(first['searched'],5);self.assertEqual(first['possible'],15)
        combinations=set()
        for row in first['candidates']:
            self.assertEqual(set(row['changes']),{'gain','boots_price'})
            self.assertIn(row['changes']['gain'],[2,4,6,8,10])
            self.assertIn(row['changes']['boots_price'],[1,2,3])
            combinations.add(tuple(sorted(row['changes'].items())))
        self.assertEqual(len(combinations),5)

    def test_bad_search_ranges_rejected(self):
        for spec in ({'ranges':{}},{'target':float('inf'),'ranges':{'gain':{}}},
                     {'ranges':{'turns':{'min':0,'max':0,'step':1}}},
                     {'ranges':{'gain':{'min':1,'max':3,'step':0}}}):
            with self.assertRaises(ValueError):search(Settings(),spec)

    def test_manual_target_can_enforce_one_sided_targets(self):
        s=self.quiet(turns=2,zone2_start=3,zone3_start=3,retreat_start=2,farm_visits=0)
        spec=dict(metric='avg_score',target=8,tolerance=0,budget=5,trials=50,confirmation=200,
                  ranges={'loot_per_depth':{'min':1,'max':5,'step':1}})
        for mode,expected in (('at_least',9),('at_most',6)):
            with self.subTest(mode=mode):
                answer=search(s,dict(spec,mode=mode))
                self.assertTrue(answer['matched'])
                self.assertEqual(answer['recommendations'][0]['validation_value'],expected)
                self.assertEqual(answer['recommendations'][0]['validation_error'],0)
                self.assertEqual(answer['validation_baseline']['player_runs'],200)

    def test_deck_target_skips_invalid_pairs_and_uses_whole_matches(self):
        settings=settings_from(dict(dice_rules=1,players=3,turns=1,retreat_start=2))
        answer=search(settings,dict(metric='zone3_p95_draws',target=45,mode='at_most',
                                    budget=10,trials=50,confirmation=200,ranges={
            'deck_monsters3':{'min':16,'max':18,'step':1},
            'deck_treasures3':{'min':27,'max':29,'step':1},
        }))
        self.assertEqual((answer['searched'],answer['skipped']),(6,3))
        self.assertEqual(answer['baseline']['games'],17)
        self.assertEqual(answer['validation_baseline']['games'],67)
        self.assertTrue(answer['matched'])
        self.assertTrue(all(sum(row['changes'].values())<=45 for row in answer['candidates']))

    def test_no_mining_produces_no_timing_estimate_and_rejects_inactive_metric(self):
        settings=settings_from(dict(dice_rules=1,players=3,turns=1,retreat_start=2,start_energy=0))
        spec=dict(metric='zone3_mine_round',target=9,mode='at_most',
                  ranges={'gain':{'min':0,'max':2,'step':1}})
        answer=search(settings,spec)
        self.assertFalse(answer['matched'])
        self.assertFalse(answer['recommendations'])
        self.assertIsNone(answer['baseline']['zone3_mine_round'])
        self.assertTrue(all(row['value'] is None and row['error'] is None for row in answer['candidates']))
        with self.assertRaisesRegex(ValueError,'requires shared decks'):
            search(Settings(),spec)


class ActionEVTests(unittest.TestCase):
    def test_farm_alternative_keeps_the_same_decision_prefix(self):
        settings=replace(Settings(),seed=19,p_monster=0,p_treasure=100,p_enhance=0)
        original=run_player(settings,random.Random(19))
        change=options(original['rows'])['First farm · Zone 1'][0]
        position=next(i for i,row in enumerate(original['rows'])
                      if (row['turn'],row['step'])==(change.turn,change.step))
        alternative=run_player(settings,random.Random(19),change=change)
        self.assertTrue(alternative['change_applied'])
        self.assertEqual(alternative['rows'][:position],original['rows'][:position])
        skipped=alternative['rows'][position]
        self.assertEqual((skipped['action'],skipped['draw_count']),('Rest',0))
        self.assertEqual(skipped['position_out'],original['rows'][position]['position_in'])

    def test_shop_alternative_defers_the_selected_purchase(self):
        settings=replace(Settings(),boots_price=0,gear_priority=3,gear_slots=1)
        original=run_player(settings,random.Random(19))
        change=options(original['rows'])['Buy Boots'][0]
        alternative=run_player(settings,random.Random(19),change=change)
        self.assertTrue(alternative['change_applied'])
        self.assertFalse(any(row['turn']==change.turn and row['action']=='Buy Boots'
                             for row in alternative['rows']))

    def test_audit_is_seeded_and_uses_one_pair_per_player_per_row(self):
        settings=replace(Settings(),players=2,seed=19)
        progress=[]
        result=audit(settings,{'games':3},progress.append,lambda:False)
        self.assertEqual(result,audit(settings,{'games':3},lambda _:None,lambda:False))
        self.assertEqual((result['players'],progress[-1]['done']),(6,3))
        self.assertTrue(result['rows'])
        for row in result['rows']:
            self.assertLessEqual(row['pairs'],6)
            self.assertAlmostEqual(row['ev'],row['action_score']-row['alternative_score'])
            self.assertEqual(row['signal'],'Small sample')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def send(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        connection.request(method,path,body,headers or {})
        response=connection.getresponse();data=response.read();connection.close()
        return response.status,data

    def test_static_and_config(self):
        for path in ('/','/app.js','/styles.css','/api/config'):
            status,data=self.send('GET',path);self.assertEqual(status,200);self.assertTrue(data)

    def test_combat_preset_runs_and_exposes_the_front_in_replay(self):
        import time
        status, data = self.send('GET', '/api/combat-preset')
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual((payload['settings']['player_duels'], payload['settings']['moving_boss']), (1, 1))
        payload['settings'].update(runs=3, boss_start=1)
        status, data = self.send('POST', '/api/simulate', json.dumps(payload), {'Content-Type': 'application/json'})
        self.assertEqual(status, 202)
        identifier = json.loads(data)['id']
        for _ in range(500):
            _, data = self.send('GET', '/api/jobs/' + identifier)
            job = json.loads(data)
            if job['state'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(job['state'], 'complete', job.get('error'))
        result = job['result']
        self.assertIn('duels', result['metrics'])
        row = result['samples'][0]['rows'][0]
        self.assertEqual((row['boss']['tile'], row['boss']['threshold']), ([0, 7], 5))
        self.assertEqual(result['boss_example'][0]['tile_before'], [0, 7])

    def test_rolled_combat_preset_exposes_editable_profiles_and_fight_odds(self):
        import time
        status, payload = self.send('GET', '/api/rolled-combat-preset')
        self.assertEqual(status, 200)
        payload = json.loads(payload)
        self.assertEqual((payload['settings']['rolled_enemy_attacks'], payload['settings']['boss_hp']), (1, 32))
        payload['settings']['runs'] = 3
        status, data = self.send('POST', '/api/simulate', json.dumps(payload), {'Content-Type': 'application/json'})
        self.assertEqual(status, 202)
        identifier = json.loads(data)['id']
        for _ in range(500):
            _, data = self.send('GET', '/api/jobs/' + identifier)
            job = json.loads(data)
            if job['state'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(job['state'], 'complete', job.get('error'))
        result = job['result']
        self.assertEqual(len(result['settings']['monster_profiles']['3']), 3)
        self.assertEqual(len(result['enemy_odds']), 45)

    def test_strategy_balance_endpoint(self):
        import time
        status,data=self.send('GET','/api/balance-preset')
        self.assertEqual(status,200)
        payload=json.loads(data)
        self.assertEqual(payload['settings']['players'],5)
        payload['balance']=dict(games=5)
        status,data=self.send('POST','/api/balance',json.dumps(payload),
                              {'Content-Type':'application/json'})
        self.assertEqual(status,202)
        identifier=json.loads(data)['id']
        for _ in range(500):
            _,data=self.send('GET','/api/jobs/'+identifier)
            job=json.loads(data)
            if job['state']!='running':break
            time.sleep(.01)
        self.assertEqual(job['state'],'complete',job.get('error'))
        self.assertTrue(job['result']['whole_moves'])
        self.assertTrue(job['result']['gold_shops'])
        self.assertEqual(len(job['result']['comparisons']),2)

    def test_preset_endpoint_compares_current_and_finalist_on_fresh_seeds(self):
        import time
        payload=json.loads(PRESET.read_text())
        payload['presets']=dict(preset='farm_cost',screening=3,holdout=3)
        status,data=self.send('POST','/api/presets',json.dumps(payload),
                              {'Content-Type':'application/json'})
        self.assertEqual(status,202)
        identifier=json.loads(data)['id']
        for _ in range(1000):
            _,data=self.send('GET','/api/jobs/'+identifier)
            job=json.loads(data)
            if job['state']!='running':
                break
            time.sleep(.01)
        self.assertEqual(job['state'],'complete',job.get('error'))
        result=job['result']
        self.assertNotEqual(result['settings']['seed'],result['validation_seed'])
        self.assertEqual((job['progress']['done'],job['progress']['total']),(48,48))
        self.assertEqual(len(result['baseline']['holdout']['scenarios']),4)
        finalist,=result['finalists']
        self.assertEqual(finalist['changes'],{'farm_cost':3})
        for scenario in finalist['holdout']['scenarios']:
            self.assertTrue(all(0<=n<=50 for n in scenario['p95_draws']))
            self.assertGreater(scenario['p95_turn'],0)

    def test_balance_preset_serves_valid_settings_and_map(self):
        status,data=self.send('GET','/cave_balance.json')
        self.assertEqual(status,200)
        report=json.loads(data)
        self.assertGreaterEqual(report['screened'],80)
        board=board_from(report['preset_board'])
        self.assertEqual(len(board.mines),6)
        for policy in report['policies'].values():
            settings_from({**report['preset'],**policy})
        self.assertTrue(any(row['label']==report['selected'] for row in report['confirmation']))

    def test_cross_origin_and_invalid_input(self):
        status,_=self.send('POST','/api/simulate','{}',{'Content-Type':'application/json','Origin':'https://example.com'})
        self.assertEqual(status,403)
        status,_=self.send('POST','/api/simulate',json.dumps({'settings':{'gain':-1}}),{'Content-Type':'application/json'})
        self.assertEqual(status,400)
        status,_=self.send('GET','/../../server.py');self.assertEqual(status,404)

    def test_job_finishes_and_returns_numbers(self):
        import time
        status,data=self.send('POST','/api/simulate',json.dumps({'settings':{'runs':2}}),{'Content-Type':'application/json'})
        self.assertEqual(status,202);identifier=json.loads(data)['id']
        for _ in range(100):
            status,data=self.send('GET','/api/jobs/'+identifier);job=json.loads(data)
            if job['state']!='running':break
            time.sleep(.01)
        self.assertEqual(job['state'],'complete')
        self.assertEqual(job['result']['metrics']['player_runs'],8)

    def test_route_study_api_runs_both_retreat_policies(self):
        import time
        payload=json.dumps({'settings':{'players':1},'study':{'kind':'retreat','games':1}})
        status,data=self.send('POST','/api/study',payload,{'Content-Type':'application/json'})
        self.assertEqual(status,202)
        identifier=json.loads(data)['id']
        for _ in range(100):
            _,data=self.send('GET','/api/jobs/'+identifier)
            job=json.loads(data)
            if job['state']!='running':break
            time.sleep(.01)
        self.assertEqual(job['state'],'complete')
        self.assertEqual([row['label'] for row in job['result']['rows']],['Fixed turn','Energy-aware'])

    def test_action_audit_api_returns_paired_decisions(self):
        import time
        payload=json.dumps({'settings':{'players':1},'audit':{'games':1}})
        status,data=self.send('POST','/api/audit',payload,{'Content-Type':'application/json'})
        self.assertEqual(status,202)
        identifier=json.loads(data)['id']
        for _ in range(100):
            _,data=self.send('GET','/api/jobs/'+identifier)
            job=json.loads(data)
            if job['state']!='running':break
            time.sleep(.01)
        self.assertEqual(job['state'],'complete',job)
        self.assertEqual(job['result']['players'],1)
        self.assertTrue(job['result']['rows'])


if __name__=='__main__':unittest.main()
