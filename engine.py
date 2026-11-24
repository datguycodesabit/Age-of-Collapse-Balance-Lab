"""Reproducible experiments, metrics and bounded target search. No dependencies."""
import itertools
import math
import random
import statistics
from dataclasses import asdict, replace
from model import (Settings, Board, DEFAULT_BOARD, GEAR, POTIONS, GATES,
                   combat, run_player, validate, boss_timeline, path_between, zone_at, detour_steps,
                   player_result, return_turns_needed)
import zone_decks
import dice_rules
from enemy_profiles import odds_table
from adaptive_route import adaptive_action, pick_plan
from development_metrics import DevelopmentMetrics

METRICS = {
    'escape_rate': ('Escape rate', '%', 0, 100),
    'voluntary_escape_rate': ('Voluntary escape rate', '%', 0, 100),
    'avg_score': ('Average banked score', 'points', 0, None),
    'zone3_rate': ('Reached Zone 3', '%', 0, 100),
    'avg_knockdowns': ('Knockdowns per player', 'knockdowns', 0, None),
    'avg_farm_actions': ('Farm activations per player', 'activations', 0, None),
    'avg_boss_ejections': ('Boss ejections per player', 'ejections', 0, None),
}
TARGET_DETAILS = {}


def target_metric(key,label,unit,group,target,tolerance,mode='near',maximum=None,requires=None,help_text=''):
    METRICS[key]=(label,unit,0,maximum if maximum is not None else 100 if unit=='%' else None)
    TARGET_DETAILS[key]=dict(group=group,target=target,tolerance=tolerance,mode=mode,
                             requires=requires,help=help_text)


for key,group,target,tolerance in (
    ('avg_score','Banking and score',10,1),('escape_rate','Banking and score',65,3),
    ('voluntary_escape_rate','Banking and score',65,3),('zone3_rate','Zone access',60,3),
    ('avg_knockdowns','Combat and collapse',1,.2),('avg_farm_actions','Mining',10,1),
    ('avg_boss_ejections','Combat and collapse',1,.2)):
    label,unit,_,maximum=METRICS[key]
    target_metric(key,label,unit,group,target,tolerance,maximum=maximum)

target_metric('positive_score_rate','Finish with banked gold','%','Banking and score',70,3,'at_least')
target_metric('median_score','Median qualifying score','gold','Banking and score',12,1)
target_metric('p90_score','90th-percentile qualifying score','gold','Banking and score',30,2)
target_metric('first_bank_median','Median first bank round','rounds','Banking and score',6,0,'at_most',
              help_text='Among players who made a positive deposit.')
target_metric('avg_unbanked','Unbanked gold per player','gold','Banking and score',3,0,'at_most')
target_metric('boss_death_rate','Killed by the boss','%','Combat and collapse',5,0,'at_most')
target_metric('avg_combat_energy','Combat Energy spent per player','Energy','Combat and collapse',6,1,'at_most')
target_metric('avg_mine_actions','Regular mine activations per player','activations','Mining',2,.2,'at_least',
              requires='shared')
target_metric('regular_miner_rate','Players using a regular mine','%','Mining',40,3,'at_least',requires='shared')
target_metric('avg_movement_energy','Walking Energy spent per player','Energy','Movement and gear',8,1,'at_most')
for item in ('Boots','Sword','Shield'):
    target_metric(f'{item.lower()}_use_rate',f'Players buying and using {item}','%','Movement and gear',
                  30,3,'at_least',requires='dice')
for zone in (1,2,3):
    if zone!=3:
        target_metric(f'zone{zone}_rate',f'Reached Zone {zone}','%','Zone access',80 if zone==1 else 60,3,'at_least')
    target_metric(f'zone{zone}_entry_round',f'First entry into Zone {zone}','rounds','Zone access',
                  (2,5,9)[zone-1],.5,'at_most',help_text='Average among players who entered the zone.')
    target_metric(f'zone{zone}_mine_rate',f'Mined in Zone {zone}','%','Mining',
                  (70,50,30)[zone-1],3,'at_least',requires='shared')
    target_metric(f'zone{zone}_mine_round',f'First mine in Zone {zone}','rounds','Mining',
                  (3,6,10)[zone-1],.5,'at_most',requires='shared',help_text='Average among players who drew a card from a site in the zone.')
    target_metric(f'zone{zone}_bank_rate',f'Mined Zone {zone}, banked later and finished on Surface','%','Banking and score',
                  (65,45,25)[zone-1],3,'at_least',requires='shared',
                  help_text='Share of all seats. A later deposit can include gold found in other zones.')
    target_metric(f'zone{zone}_p95_draws',f'Zone {zone} 95th-percentile deck draws','cards','Deck reserves',
                  45,0,'at_most',maximum=50,requires='shared',help_text='A target of 45 leaves at least five cards in roughly 95% of matches.')
    target_metric(f'zone{zone}_depletion_rate',f'Zone {zone} deck emptied','%','Deck reserves',
                  5,0,'at_most',requires='shared')
TUNABLE = {'start_energy', 'gain', 'cap', 'retreat_start', 'lose_loot',
           'hp1', 'hp2', 'hp3', 'atk1', 'atk2', 'atk3', 'loot_per_depth','deep_cache_loot',
           'delve', 'retreat', 'enhance','boots_price','flashlight_price','climbing_price',
           'dark_cost','rough_cost','farm_visits','farm_cost','boss_start','boss_threshold',
           'boss_loot_loss','boss_energy_hit','buy_boots','buy_flashlight','buy_climbing','boss_enabled'}
TUNABLE.update(key for keys in GEAR.values() for key in keys)
TUNABLE.update({'gear_slots','max_zone','gear_priority','potion_chance','use_potions','deep_entry_tonic'})
TUNABLE.update({'adaptive_retreat','retreat_slack','farm_detour_limit'})
TUNABLE.update({'mine_cost','blade_savings','pack_protection','charm_bonus','battery_gain'})
TUNABLE.update({'sword_savings','shield_savings','upgrade_price','bow_savings',
                'grenade_savings','canister_gain','energy_potion_gain'})
TUNABLE.update({'sword_price','shield_price','lose_depth'})
TUNABLE.update({'farm_shared_limit','deep_tonic_energy','boots_move_range','shield_block_per_level'})
TUNABLE.update({'turns','players','sword_damage_bonus','field_starter_gear','shop_gold_prices',
                'full_energy_moves','zone2_start','zone3_start'})
TUNABLE.update(f'{prefix}{zone}' for prefix in ('hp_min','hp_max','treasure_min','treasure_max','bounty',
                                               'deck_monsters','deck_treasures')
               for zone in (1,2,3))

# Best candidate in tune_equipment.py --players 280, checked on seed 20271090.
GEAR_BALANCE_PRICES = {
    'boots_price':3, 'flashlight_price':3, 'climbing_price':2, 'pick_price':3,
    'pack_price':2, 'blade_price':4, 'charm_price':2, 'battery_price':4,
    'map_price':2, 'harness_price':4,
}

ESCAPE_TEST_SETUP = {
    'board': {
        'rows':['....S.','....S#','.M..M.','F..#..','..M...',
                '.M...F','....S.','###MS.','#.#F.M','....#.'],
        'gates':[4,0,4],
        'shop_detours':False,
    },
    'settings':{'boss_start':11,'boss_threshold':3,'retreat_start':14,'adaptive_retreat':1,'retreat_slack':1},
}


def board_from(data):
    if data is None:
        return DEFAULT_BOARD
    if not isinstance(data,dict):
        raise ValueError('Send a map object.')
    rows, columns = data.get('rows'), data.get('gates')
    detours = data.get('shop_detours', False)
    if not isinstance(columns,list) or len(columns)!=3 or any(type(x) is not int or not 0<=x<6 for x in columns):
        raise ValueError('Choose one gate column for each of the three boundaries.')
    if (not isinstance(rows,list) or len(rows)!=10
        or any(not isinstance(row,str) or len(row)!=6 or set(row)-set('.#FSM') for row in rows)):
        raise ValueError('Map needs ten rows of six symbols. Use . # F M or S.')
    if type(detours) is not bool:
        raise ValueError('Shop detours must be enabled or disabled.')
    tiles = {(x,y):mark for y,row in enumerate(rows) for x,mark in enumerate(row)}
    farms = [coord for coord,mark in tiles.items() if mark=='F']
    if any(zone_at(tile)==0 for tile in farms):
        raise ValueError('Place farms underground.')
    shops = frozenset(coord for coord,mark in tiles.items() if mark=='S')
    rocks = frozenset(coord for coord,mark in tiles.items() if mark=='#')
    mines = frozenset(coord for coord,mark in tiles.items() if mark=='M')
    if any(zone_at(tile)==0 for tile in mines):
        raise ValueError('Place regular mines underground.')
    board = Board(tuple(columns),tuple(farms),shops,rocks,detours,mines)
    for zone in range(1,4):
        if board.entrance(zone) in rocks or board.exit(zone-1) in rocks:
            raise ValueError('Both tiles of the Zone %s gate must be open.'%zone)
    for coord in tiles.keys()-rocks:
        if not path_between(board.start,coord,(),board):
            raise ValueError('Open tile at column %s, depth row %s is cut off from Surface.'%(coord[0]+1,coord[1]))
    return board


def board_metadata(board=DEFAULT_BOARD):
    rows=[''.join('#' if (x,y) in board.rocks else 'F' if (x,y) in board.farms else 'M' if (x,y) in board.mines
                  else 'S' if (x,y) in board.shops else '.' for x in range(6)) for y in range(10)]
    route=[board.start]
    distances=[]
    farm_distances=[]
    for zone in (1,2,3):
        entry=board.entrance(zone)
        approach=path_between(route[-1],entry,(),board)
        route.extend(approach[1:])
        farms=board.farms_in(zone)
        rows_for_zone=[]
        for farm in farms:
            farm_path=path_between(entry,farm,(),board)
            nearby=[len(path_between(farm,shop,(),board))-1 for shop in board.shops if zone_at(shop)==zone]
            exit_path=path_between(farm,board.exit(zone),(),board) if zone<3 else ()
            home=path_between(farm,board.start,(),board)
            rows_for_zone.append(dict(zone=zone,tile=farm,gate_to_farm=len(farm_path)-1,
                                      farm_to_gate=len(exit_path)-1 if exit_path else None,
                                      farm_detour=detour_steps(board,zone,farm) if zone<3 else None,
                                      farm_to_shop=min(nearby,default=None),farm_to_surface=len(home)-1))
        if farms:
            route.extend(path_between(entry,farms[0],(),board)[1:])
            distances.append(rows_for_zone[0])
            farm_distances.extend(rows_for_zone)
        else:
            distances.append(dict(zone=zone,tile=None,gate_to_farm=None,farm_to_gate=None,
                                  farm_detour=None,farm_to_shop=None,farm_to_surface=None))
    deepest=max((row['zone'] for row in farm_distances),default=0)
    deepest_return=max((row['farm_to_surface'] for row in farm_distances if row['zone']==deepest),default=None)
    return dict(width=6,height=10,start=board.start,
                farms={str(zone):board.primary_farm(zone) for zone in (1,2,3)},
                farm_sites=board.farms,farm_distances=farm_distances,
                shops=sorted(board.shops),mines=sorted(board.mines),gates=dict(zip(GATES,board.gates)),distances=distances,
                route=route,route_steps=len(route)-1,deepest_return_steps=deepest_return,
                layout=dict(rows=rows,gates=list(board.gates),shop_detours=board.shop_detours),version=3)


def settings_from(data):
    if not isinstance(data, dict):
        raise ValueError('Settings must be an object.')
    defaults = asdict(Settings())
    if data.get('shared_decks')==1:
        defaults.update(zone_decks.DEFAULTS)
    if data.get('dice_rules')==1:
        defaults.update(dice_rules.DEFAULTS)
    if 'steps_per_turn' in data: raise ValueError('Fixed step limits were removed. Reload the app or import your saved settings to migrate them.')
    if set(data)-set(defaults): raise ValueError('Unknown setting.')
    for key, value in data.items():
        if key in ('treasure_profiles', 'monster_profiles'):
            defaults[key]=value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('%s must be a finite number.' % key)
        if isinstance(defaults[key], int) and int(value) != value:
            raise ValueError('%s must be a whole number.' % key)
        defaults[key] = int(value) if isinstance(defaults[key], int) else float(value)
    s = Settings(**defaults)
    validate(s)
    if s.dice_rules:
        dice_rules.deck_composition(s)
    if s.seed > 2**53-1:
        raise ValueError('Seed must be at most 9007199254740991.')
    if max(abs(v) for k,v in defaults.items() if k not in ('seed','treasure_profiles','monster_profiles')) > 1000000:
        raise ValueError('Setting values must be at most 1,000,000.')
    return s


def wilson(successes, count):
    z = 1.96
    p = successes/count
    denom = 1+z*z/count
    middle = (p+z*z/(2*count))/denom
    half = z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/denom
    return [max(0, 100*(middle-half)), min(100, 100*(middle+half))]


def shared_game(s, board, game_index, players, cancel, depths=None):
    """Play one seeded match with bots using the same legal actions as agents."""
    # AgentMatch imports settings and layout parsing from this module.
    from agent_match import AgentMatch

    seed = (s.seed + game_index * 15485863) % (2**53)
    settings = replace(s, seed=seed, players=players)
    match = AgentMatch(asdict(settings), board_metadata(board)['layout'])
    retreating = set()
    while not match.complete:
        if cancel and cancel():
            raise InterruptedError('Experiment cancelled.')
        actor = match.active
        player = match.players[actor]
        # Retreat is a commitment for the rest of the match.
        if s.adaptive_retreat and player.visited:
            needed = return_turns_needed(player, s, match.closed)
            if needed is None or needed + s.retreat_slack >= s.turns - match.round:
                retreating.add(actor)
        elif not s.adaptive_retreat and match.round >= s.retreat_start:
            retreating.add(actor)
        actions = match.legal_actions(actor)
        if s.dice_rules and depths is None:
            plan = pick_plan(match, returning=actor in retreating)
            action = adaptive_action(match, plan, actions)
        elif s.dice_rules:
            action = dice_rules.automated_choice(match, actions, depths[actor], actor in retreating)
        else:
            action = zone_decks.automated_choice(match, actions, actor in retreating)
        # The policy chose from the current legal list, so skip a second enumeration.
        match._commit(dict(actor=actor,revision=match.revision,action=action))

    results = []
    for player, rows in zip(match.players, match.logs):
        for _, turn_rows in itertools.groupby(rows, key=lambda row: row['turn']):
            for step, row in enumerate(turn_rows, start=1):
                row['step'] = step
        result = player_result(player, rows, match.closed)
        if s.dice_rules:
            # Forfeited final banks remain visible in replay, but cannot score.
            result['score'] = player.bank if player.escaped else 0
        if s.moving_boss:
            result['surface'] = player.escaped and zone_at(player.position) == 0
            result['boss_slayer'] = match.boss_defeated_by == len(results)
        results.append(result)
    return match._schedule, results


def check_experiment_budget(s,count):
    if not 1 <= count <= 50000 or count*s.turns*(2*s.cap+2*s.farm_visits+8)>4000000:
        raise ValueError('Experiment too large: reduce games, players, turns, energy cap or farming quota (work budget 4 million).')


def experiment(s, sample_limit=40, player_count=None, cancel=None, board=DEFAULT_BOARD):
    """Run seeded games and aggregate player outcomes for the viewer and searches.

    Shared decks require a complete match before any seat can be scored. In the
    older independent-draw mode, seats share only their game's boss timeline.
    """
    validate(s)
    count = s.runs*s.players if player_count is None else player_count
    check_experiment_budget(s,count)
    scores, players, samples = [], [], []
    turns = [dict(turn=t, energy=0, distance=0, reachable=0, active=0, extracted=0) for t in range(1,s.turns+1)]
    development=DevelopmentMetrics(s)
    escape_count = knocks = waits = penalties = discovered = lost = 0
    extraction_turns = []
    worlds={}
    equipment_counts=dict.fromkeys(GEAR,0)
    gear_use_counts=dict.fromkeys(GEAR,0)
    potion_counts={name:dict(label=name,found=0,used=0) for name in POTIONS}
    farm_total=encounters=gear_spent=ejections=killed=movement=boss_losses=0
    duels = boss_attempts = boss_wins = surface_count = 0
    cache_claims=0
    mine_total=empty_draws=0
    card_counts=dict.fromkeys(('Treasure','Monster','Enhancement','Nothing'),0)
    item_counts=dict.fromkeys(zone_decks.ITEMS,0) if s.shared_decks else {}
    if s.shared_decks:
        card_counts.pop('Enhancement')
        card_counts['Item']=0
    walking_energy=0
    gear_walking_savings=dict.fromkeys(GEAR,0)
    diagnostics=dict(gates=[0,0,0],gate_turns=[0,0,0],stranded=[0,0,0,0],boss_deaths=[0,0,0,0],
                     farm_turns=0,shop_turns=0,shop_steps=0,waits={name:0 for name in
                     ('Dark gate','Gate','Farm','Walking')})
    for index in range(count):
        if cancel and cancel():
            raise InterruptedError('Search cancelled.')
        game_index=index//s.players
        if s.shared_decks:
            if game_index not in worlds:
                worlds[game_index],game_players=shared_game(s,board,game_index,min(s.players,count-index),cancel)
            p=game_players[index%s.players]
        else:
            if game_index not in worlds:
                worlds[game_index]=boss_timeline(s,random.Random(s.seed+700000003+game_index*15485863))
            player_seed=s.seed+index*104729
            p = run_player(s, random.Random(player_seed),worlds[game_index],player_seed+535013,board)
        rows = p['rows']
        first_bank_round=development.record_player(game_index,p)
        gate_turns={}
        farm_turns=set()
        shop_turns=set()
        for row in rows:
            action=row['action']
            duels += action == 'Challenge'
            boss_attempts += bool(row.get('boss_attempt'))
            boss_wins += bool(row.get('boss_defeated'))
            cache_claims+=row['cache_loot']>0
            empty_draws+=row['empty_draws']
            for card in row['cards']: card_counts[card]+=1
            for item in row.get('items_found',()): item_counts[item]+=1
            if action in ('Delve','Retreat'):
                walking_energy+=row['action_cost']
                if action=='Delve' and row['start_depth']<row['zone']:
                    gate_turns.setdefault(row['zone'],row['turn'])
            if action in ('Farm','Mine'): farm_turns.add(row['turn'])
            if row['route_goal']=='Shop' or action.startswith('Buy '):
                shop_turns.add(row['turn'])
                diagnostics['shop_steps']+=action=='Delve'
            if row['wait_for']: diagnostics['waits'][row['wait_for']]+=1
            for item,saving in row['walking_savings'].items(): gear_walking_savings[item]+=saving
        for zone,turn in gate_turns.items():
            diagnostics['gates'][zone-1]+=1
            diagnostics['gate_turns'][zone-1]+=turn
        diagnostics['farm_turns']+=len(farm_turns)
        diagnostics['shop_turns']+=len(shop_turns)
        if p['killed']: diagnostics['boss_deaths'][p['depth']]+=1
        elif not p['escaped']: diagnostics['stranded'][p['depth']]+=1
        deepest = max(r['zone'] for r in rows)
        score = p['score']
        scores.append(score)
        escape_count += p['escaped']
        knocks += p['knockdowns']
        waits += sum(r['action']=='Wait' for r in rows)
        penalties += sum(r['loot_penalty'] for r in rows if r['knockdown']=='Yes' and not r.get('duel'))
        boss_losses += sum(r['loot_penalty'] for r in rows if r['boss_ejection'] or r['action']=='Killed by boss')
        discovered += p['visited']
        lost += p['carried'] if not p['escaped'] or p.get('boss_slayer') else 0
        farm_total+=p['farm_actions'];mine_total+=p['mine_actions'];encounters+=p['encounters'];gear_spent+=p['equipment_spent']
        ejections+=p['boss_ejections'];killed+=p['killed'];movement+=p['movement_steps']
        for item in p['equipment']: equipment_counts[item]+=1
        for item in p['gear_used']: gear_use_counts[item]+=1
        for item in p['potions_found']: potion_counts[item]['found']+=1
        for item in p['potions_used']: potion_counts[item]['used']+=1
        if p['escaped']: extraction_turns.append(p['turns'])
        last_by_turn = {r['turn']:r for r in rows}
        for point in turns:
            row = last_by_turn.get(point['turn'])
            if row:
                point['energy'] += row['end_energy']
                if row['distance_home'] is not None:
                    point['distance']+=row['distance_home']
                    point['reachable']+=1
                point['active'] += 1
            point['extracted'] += bool(p['escaped'] and p['turns'] <= point['turn'])
        summary = dict(game=index//s.players+1, player=index%s.players+1,
                       score=score, escaped=p['escaped'], knockdowns=p['knockdowns'],
                       turns=p['turns'], deepest_zone=deepest, distance_home=p['distance_home'],
                       carried=p['carried'], visited=p['visited'],equipment=p['equipment'],
                       equipment_spent=p['equipment_spent'],farm_actions=p['farm_actions'],mine_actions=p['mine_actions'],
                       encounters=p['encounters'],boss_ejections=p['boss_ejections'],killed=p['killed'],
                       first_bank_round=first_bank_round)
        summary.update(potions_found=len(p['potions_found']),potions_used=len(p['potions_used']),
                       gear_used=p['gear_used'])
        if s.shared_decks:
            summary.update(sword=next((row['sword'] for row in reversed(rows) if 'sword' in row),0 if s.dice_rules else 1),
                           shield=next((row['shield'] for row in reversed(rows) if 'shield' in row),0))
        if s.moving_boss:
            surface_count += p['surface']
            summary.update(surface=p['surface'], boss_slayer=p['boss_slayer'])
        players.append(summary)
        if index < sample_limit: samples.append(dict(**summary, rows=rows,boss_timeline=worlds[game_index]))
    no_survivors=0
    for offset in range(0,count,s.players):
        game=players[offset:offset+s.players]
        best=max((p['score'] for p in game if p['escaped']),default=None)
        no_survivors+=best is None
        for p in game: p['winner']=bool(p['escaped'] and p['score']==best)
    for point in turns:
        active = point['active']
        point['energy'] = point['energy']/active if active else None
        point['distance'] = point['distance']/point['reachable'] if point['reachable'] else None
        point['extracted_pct'] = 100*point['extracted']/count
    mean = statistics.mean(scores)
    sem = statistics.stdev(scores)/math.sqrt(count) if count > 1 else 0
    escape_ci=wilson(escape_count,count);ci_method='Independent-player approximation'
    if s.boss_enabled or s.shared_decks:
        # Shared boss rolls correlate players in one game. Use independent games
        # as clusters rather than treating those players as independent evidence.
        ci_method='Game-cluster approximation'
        groups=[players[i:i+s.players] for i in range(0,count,s.players)]
        if len(groups)>1:
            g=len(groups)
            sem=math.sqrt(g/(g-1)*sum(sum(p['score']-mean for p in group)**2 for group in groups))/count
            rate=escape_count/count
            rate_sem=math.sqrt(g/(g-1)*sum(sum(p['escaped']-rate for p in group)**2 for group in groups))/count
            escape_ci=[max(0,min(escape_ci[0],100*(rate-1.96*rate_sem))),
                       min(100,max(escape_ci[1],100*(rate+1.96*rate_sem)))]
        else:
            sem=None;escape_ci=[0,100]
    metrics = dict(player_runs=count, games=count/s.players, escaped=escape_count,
                   escape_rate=100*escape_count/count, escape_ci=escape_ci,ci_method=ci_method,
                   avg_score=mean, score_ci=[max(0,mean-1.96*sem),mean+1.96*sem] if sem is not None else [None,None],
                   median_score=statistics.median(scores), max_score=max(scores),
                   zero_score_rate=100*scores.count(0)/count,
                   cache_claim_rate=100*cache_claims/count,
                   avg_knockdowns=knocks/count,
                   avg_waits=waits/count, avg_discovered=discovered/count,
                   avg_unbanked=lost/count, avg_loot_penalty=penalties/count,
                   avg_boss_loot_penalty=boss_losses/count,
                   avg_farm_actions=farm_total/count,avg_mine_actions=mine_total/count,avg_encounters=encounters/count,
                   card_counts=card_counts,empty_draws=empty_draws,
                   item_counts=item_counts,
                   avg_equipment_spent=gear_spent/count,avg_boss_ejections=ejections/count,
                   boss_death_rate=100*killed/count,voluntary_escape_rate=100*escape_count/count,
                   avg_score_survivors=sum(scores)/escape_count if escape_count else None,
                   no_survivor_game_rate=100*no_survivors/len(worlds),
                   avg_movement_steps=movement/count,
                   avg_movement_energy=walking_energy/count,
                   avg_escape_turn=statistics.mean(extraction_turns) if extraction_turns else None)
    width = max(1, math.ceil((max(scores)+1)/12))
    hist = [dict(low=i*width, high=(i+1)*width-1, count=0) for i in range(12)]
    for score in scores: hist[min(11,score//width)]['count'] += 1
    advice = []
    metadata=board_metadata(board)
    if metadata['deepest_return_steps'] is not None:
        advice.append('The longest farm return in the deepest farm zone is %s steps.'%metadata['deepest_return_steps'])
    if metrics['avg_waits'] > 0.5:
        advice.append('Players wait %.2f times on average for movement energy. Test higher energy gain/cap or lower step costs.' % metrics['avg_waits'])
    if metrics['avg_knockdowns'] > 1:
        advice.append('Combat causes %.2f knockdowns per player. Test lower monster attacks/HP or higher energy capacity.' % metrics['avg_knockdowns'])
    if metrics['avg_unbanked'] > mean:
        advice.append('More loot is stranded than banked. Test retreat timing before raising treasure rewards.')
    if ejections or killed:
        advice.append('The boss forced %.2f deeper-zone ejections per player and killed %.1f%% of players by sealing the entrance.'%(ejections/count,100*killed/count))
    advice.append('Gear costs %.2f loot per player on average. Test buying switches or prices to compare the value of movement savings against banked score.'%(gear_spent/count))
    if metrics['escape_rate'] > 95:
        advice.append('Escape exceeds 95%. If you want more risk, test later retreat or stronger monsters in the target finder.')
    if not advice:
        advice.append('Use Find a balance to test a specific goal. The closest sampled setting is an estimate, not a guaranteed optimum.')
    diagnostics['gate_turns']=[total/reached if reached else None
                              for total,reached in zip(diagnostics['gate_turns'],diagnostics['gates'])]
    for field in ('farm_turns','shop_turns','shop_steps'): diagnostics[field]/=count
    report=development.report(count,len(worlds))
    metrics.update(positive_score_rate=100*report['outcomes']['scored']/count,
                   p90_score=sorted(scores)[math.ceil(.9*count)-1],
                   first_bank_median=report['first_bank_median'],
                   avg_combat_energy=report['energy']['combat'],
                   regular_miner_rate=100*report['regular_miners']/count)
    if s.player_duels or s.moving_boss:
        metrics.update(duels=duels, boss_attempts=boss_attempts, boss_wins=boss_wins,
                       surface_rate=100*surface_count/count if s.moving_boss else metrics['escape_rate'])
    for row in report['zones']:
        prefix=f"zone{row['zone']}_"
        metrics.update({prefix+'rate':100*row['entered']/count,
                        prefix+'entry_round':row['entry_round'],
                        prefix+'mine_rate':100*row['mined']/count,
                        prefix+'mine_round':row['mine_round'],
                        prefix+'bank_rate':100*row['qualified_after_mining']/count})
        if s.shared_decks:
            metrics.update({prefix+'p95_draws':row['p95_draws'],
                            prefix+'depletion_rate':100*row['exhausted']/len(worlds)})
    for item in report['gear']:
        metrics[item['item'].lower()+'_use_rate']=100*item['used']/count
    return dict(settings=asdict(s), metrics=metrics, histogram=hist, timeline=turns,diagnostics=diagnostics,
                enemy_odds=odds_table(s) if s.rolled_enemy_attacks else [],
                development=report,
                board=metadata,equipment_rates=[
                    dict(label=k,count=v,percent=100*v/count,used=gear_use_counts[k],
                         used_percent=100*gear_use_counts[k]/count,walking_energy_saved=gear_walking_savings[k]/count)
                    for k,v in equipment_counts.items()],
                potion_rates=list(potion_counts.values()),
                collapse_rates=[dict(zone=z,percent=100*sum(bool(w) and z in w[-1]['closed'] for w in worlds.values())/len(worlds)) for z in (1,2,3)],
                boss_example=worlds[0],
                reach=[dict(zone=row['zone'],count=row['entered'],percent=100*row['entered']/count)
                       for row in report['zones']],
                samples=samples, players=players, advice=advice,
                combat=[dict(zone=z,hp_min=getattr(s,f'hp_min{z}'),hp_max=getattr(s,f'hp_max{z}'),
                             attack=getattr(s,f'atk{z}'),bounty=getattr(s,f'bounty{z}'))
                        if s.dice_rules else dict(zone=z,hp=combat(z,s)[0],attack=combat(z,s)[1],
                                                 rounds=combat(z,s)[2],energy=combat(z,s)[3])
                        for z in (1,2,3)])


def farm_variants(board,zone):
    """Move just one farm, choosing the nearest tile for each exact detour."""
    entry=board.entrance(zone)
    original=board.primary_farm(zone)
    if original is None:
        raise ValueError(f'Place a farm in Zone {zone} before comparing farm detours.')
    candidates={}
    for y in range(entry[1],entry[1]+3):
        for x in range(6):
            point=(x,y)
            if (point in board.rocks or point in board.shops or point in board.mines
                    or point!=original and point in board.farms): continue
            detour=detour_steps(board,zone,point)
            if detour in (2,4,6):
                candidates.setdefault(detour,[]).append(point)
    for detour in (2,4,6):
        points=candidates.get(detour)
        if not points:
            yield detour,None
            continue
        point=min(points,key=lambda p:(len(path_between(original,p,(),board)),p))
        yield detour,board.move_farm(original,point)


def generated_maps(board,seed,count):
    """Sample single-gate layouts with the same farm and vendor counts per zone."""
    rng=random.Random(seed+834755)
    shops_per_zone=[sum(zone_at(p)==zone for p in board.shops) for zone in range(4)]
    seen={board}
    for attempt in range(count*20):
        gates=tuple(rng.sample(range(6),3))
        if attempt%2==0:
            gates=rng.choice(((rng.randrange(2),rng.randrange(4,6),rng.randrange(2)),
                              (rng.randrange(4,6),rng.randrange(2),rng.randrange(4,6))))
        floor=Board(gates=gates)
        gate_tiles={coord for z in (1,2,3) for coord in (floor.entrance(z),floor.exit(z-1))}
        far_columns=[tuple(x for x in range(6) if abs(x-gate)>=3) for gate in (gates[1],gates[2],gates[2])]
        farms=[]
        for zone,columns in enumerate(far_columns,1):
            amount=len(board.farms_in(zone))
            if amount:
                first=(rng.choice(columns),3*zone-rng.randrange(2))
                tiles=[(x,y) for x in range(6) for y in range(3*zone-2,3*zone+1)
                       if (x,y)!=first]
                farms.extend([first,*rng.sample(tiles,amount-1)])
        farms=tuple(sorted(farms,key=lambda tile:(tile[1],tile[0])))
        shops=set()
        for zone,amount in enumerate(shops_per_zone):
            tiles=[(x,y) for y in range(10) for x in range(6) if zone_at((x,y))==zone and (x,y) not in farms]
            # Some layouts keep vendors by a gate, others put them on a side trip.
            rng.shuffle(tiles)
            if attempt%3!=0:
                tiles.sort(key=lambda tile:tile not in gate_tiles)
            shops.update(tiles[:amount])
        vacant=[(x,y) for y in range(1,10) for x in range(6)
                if (x,y) not in gate_tiles and (x,y) not in farms and (x,y) not in shops]
        mines=set()
        for zone in (1,2,3):
            sites=[tile for tile in vacant if zone_at(tile)==zone]
            rng.shuffle(sites)
            sites.sort(key=lambda tile:abs(tile[0]-gates[zone-1]))
            if sites:
                mines.update((sites[0],sites[-1]))
        rock_sites=[tile for tile in vacant if tile not in mines]
        rocks=frozenset(rng.sample(rock_sites,min(len(rock_sites),rng.choice((0,2,4,6,8,10)))))
        candidate=Board(gates,farms,frozenset(shops),rocks,board.shop_detours,frozenset(mines))
        if candidate in seen:
            continue
        if not all(path_between(candidate.start,(x,y),(),candidate)
                   for y in range(10) for x in range(6) if (x,y) not in rocks):
            continue
        seen.add(candidate)
        yield candidate
        if len(seen)>count:
            return


def map_study(s,spec,progress,cancel,board):
    budget=spec.get('maps',48)
    games=spec.get('games',40)
    if type(budget) is not int or not 4<=budget<=96 or type(games) is not int or not 1<=games<=250:
        raise ValueError('Use 4–96 maps and 1–250 games per map.')
    if budget*games*s.players>40000:
        raise ValueError('Reduce maps, games, or players to keep screening under 40,000 players per policy.')
    target=spec.get('target',75)
    if type(target) not in (int,float) or not math.isfinite(target) or not 0<=target<=100:
        raise ValueError('Escape target must be 0–100%.')
    late_turn=max(s.retreat_start,s.turns-1)
    candidates=[board,*generated_maps(board,s.seed,budget-1)]
    finalists=min(5,len(candidates)-1)
    total=len(candidates)+finalists+1

    def measure(layout,settings,label):
        careful=experiment(replace(settings,adaptive_retreat=1),0,cancel=cancel,board=layout)['metrics']
        late=experiment(replace(settings,adaptive_retreat=0,retreat_start=late_turn),0,
                        cancel=cancel,board=layout)['metrics']
        shape=board_metadata(layout)
        accuracy=abs(careful['escape_rate']-target)
        gap=careful['escape_rate']-late['escape_rate']
        return dict(label=label,careful=careful,late=late,gap=gap,
                    error=accuracy+max(0,10-gap),layout=shape['layout'],
                    return_steps=shape['deepest_return_steps'])

    training=replace(s,runs=games)
    explored=[]
    for index,layout in enumerate(candidates):
        explored.append(measure(layout,training,'Current layout' if index==0 else 'Map '+str(index)))
        progress(dict(phase='Screening layouts',done=index+1,total=total))
    selected=[0,*sorted(range(1,len(explored)),key=lambda i:explored[i]['error'])[:finalists]]
    confirmation=replace(s,runs=max(100,games*2),seed=(s.seed+9973) % (2**53))
    confirmed=[]
    for index,i in enumerate(selected):
        tested=measure(candidates[i],confirmation,explored[i]['label'])
        confirmed.append(tested)
        progress(dict(phase='Confirming with fresh seed',done=len(candidates)+index+1,total=total))
    return dict(kind='map',rows=[confirmed[0],*sorted(confirmed[1:],key=lambda row:row['error'])],
                tested=len(explored),target=target,games=confirmation.runs,
                players=confirmation.runs*s.players,seed=confirmation.seed,
                late_turn=late_turn,slack=s.retreat_slack)


def route_study(s,spec,progress,cancel,board):
    kind=spec.get('kind')
    if kind=='map':
        return map_study(s,spec,progress,cancel,board)
    games=spec.get('games')
    if type(games) is not int or not 1<=games<=1000:
        raise ValueError('Choose 1–1,000 games per condition.')
    base=replace(s,runs=games)
    zone=spec.get('zone',1)
    item=spec.get('item')
    if kind=='farm':
        if type(zone) is not int or zone not in (1,2):
            raise ValueError('Choose Zone 1 or 2. Both have a next gate.')
        if (not s.dice_rules and not s.farm_visits) or zone>s.max_zone:
            raise ValueError('Enable farming and allow the selected zone before comparing detours.')
        variants=[('Current map',base,board)]
        variants.extend((f'+{steps} steps',base,layout) for steps,layout in farm_variants(board,zone))
    elif kind=='retreat':
        variants=[('Fixed turn',replace(base,adaptive_retreat=0),board),
                  ('Energy-aware',replace(base,adaptive_retreat=1),board)]
    elif kind=='gear':
        if not isinstance(item,str) or item not in GEAR: raise ValueError('Choose an equipment item.')
        if s.shared_decks and item!='Boots':
            raise ValueError('Boots are the available walking equipment in shared deck mode.')
        switch=GEAR[item][1]
        variants=[('Available',replace(base,**{switch:1}),board),('Unavailable',replace(base,**{switch:0}),board)]
    elif kind=='depth':
        variants=[('Stop at Zone 2',replace(base,max_zone=2),board),
                  ('Attempt Zone 3 · no cache',replace(base,max_zone=3,deep_cache_loot=0),board)]
        if s.deep_cache_loot:
            variants.append((f'Attempt Zone 3 · {s.deep_cache_loot} cache loot',replace(base,max_zone=3),board))
    else:
        raise ValueError('Choose a farm, retreat, equipment or depth comparison.')
    rows=[]
    for index,(label,settings,layout) in enumerate(variants):
        if cancel(): raise InterruptedError('Study cancelled.')
        if layout is None:
            rows.append(dict(label=label,unavailable=True))
        else:
            result=experiment(settings,0,cancel=cancel,board=layout)
            rows.append(dict(label=label,metrics=result['metrics'],layout=result['board']['layout'],
                             farm_detour=result['board']['distances'][zone-1]['farm_detour'] if kind=='farm' else None,
                             farm=result['board']['farms'][str(zone)] if kind=='farm' else None,
                             gear=next((row for row in result['equipment_rates'] if row['label']==item),None)))
        progress(dict(phase=label,done=index+1,total=len(variants)))
    return dict(kind=kind,rows=rows,games=games,players=games*s.players,seed=s.seed,item=item)


def search(s, spec, progress=lambda value:None, cancel=lambda:False, board=DEFAULT_BOARD):
    metric = spec.get('metric','escape_rate')
    if not isinstance(metric,str) or metric not in METRICS: raise ValueError('Unknown target metric.')
    requirement=TARGET_DETAILS[metric]['requires']
    if requirement=='shared' and not s.shared_decks or requirement=='dice' and not s.dice_rules:
        raise ValueError('That metric requires '+('Dice rules.' if requirement=='dice' else 'shared decks.'))
    mode=spec.get('mode','near')
    if mode not in ('near','at_least','at_most'):
        raise ValueError('Choose a target direction.')
    target, tolerance = spec.get('target',65), spec.get('tolerance',3)
    for value in (target,tolerance):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('Target and tolerance must be finite numbers.')
    if tolerance < 0 or target < 0 or (METRICS[metric][3] is not None and target > METRICS[metric][3]):
        raise ValueError('Target outside the metric range, or negative tolerance.')
    budget = spec.get('budget',60)
    trials = spec.get('trials',200)
    confirmation = spec.get('confirmation',1000)
    for value,lo,hi in ((budget,5,150),(trials,50,1000),(confirmation,200,5000)):
        if type(value) is not int or not lo <= value <= hi: raise ValueError('Invalid search budget or sample size.')
    ranges = spec.get('ranges',{})
    if not isinstance(ranges,dict) or not 1 <= len(ranges) <= 4: raise ValueError('Choose 1–4 parameters to vary.')
    names, choices = [], []
    for name, bounds in ranges.items():
        if name not in TUNABLE: raise ValueError('This parameter cannot be searched.')
        if not isinstance(bounds,dict): raise ValueError('Invalid search range.')
        low, high, step = (bounds.get(k) for k in ('min','max','step'))
        if any(type(v) is not int for v in (low,high,step)) or step < 1 or low > high or high-low > 1000:
            raise ValueError('Use whole-number ranges, positive steps, and a span of at most 1,000.')
        values = list(range(low,high+1,step))
        names.append(name); choices.append(values)
    total = math.prod(len(c) for c in choices)
    rng = random.Random(s.seed+815)

    def grid():
        if total<=budget:
            yield from itertools.product(*choices)
            return
        indexes=rng.sample(range(total),min(total,budget*20))
        for index in indexes:
            combination=[]
            for values in reversed(choices):
                index,remainder=divmod(index,len(values))
                combination.append(values[remainder])
            yield tuple(reversed(combination))

    settings=asdict(s)
    candidates=[]
    skipped=0
    first_problem=''

    def sample_count(candidate,budget):
        # Keep shared matches complete and compare the same number of games
        # when table size is one of the searched settings.
        return math.ceil(budget/s.players)*candidate.players if s.shared_decks else budget

    for values in grid():
        if cancel():
            raise InterruptedError('Search cancelled.')
        changes=dict(zip(names,values))
        try:
            candidate=settings_from(dict(settings,**changes))
            check_experiment_budget(candidate,sample_count(candidate,max(trials,confirmation)))
        except ValueError as exc:
            skipped+=1
            first_problem=first_problem or str(exc)
            continue
        candidates.append((changes,candidate))
        if len(candidates)==budget:
            break
    if not candidates:
        raise ValueError('No legal setting combinations found. '+first_problem)

    def error(value):
        if value is None:
            return None
        if mode=='at_least':
            return max(0,target-value)
        if mode=='at_most':
            return max(0,value-target)
        return abs(value-target)

    def order(row,value_key,error_key):
        value=row[value_key]
        return (value is None,row[error_key] or 0,abs(value-target) if value is not None else 0)

    validation_seed=(s.seed+1000000007)%(2**53)
    baseline=experiment(s,0,sample_count(s,trials),cancel,board)['metrics']
    results=[]
    best=None
    for index,(changes,candidate) in enumerate(candidates):
        metrics=experiment(candidate,0,sample_count(candidate,trials),cancel,board)['metrics']
        value=metrics[metric]
        deviation=error(value)
        results.append(dict(changes=changes,value=value,error=deviation))
        if deviation is not None:
            best=deviation if best is None else min(best,deviation)
        progress(dict(phase='Exploring settings',done=index+1,total=len(candidates)+min(5,len(candidates)),
                      best=best))
    ranked=sorted((i for i,row in enumerate(results) if row['value'] is not None),
                  key=lambda i:order(results[i],'value','error'))[:5]
    validation_baseline=(experiment(replace(s,seed=validation_seed),0,sample_count(s,confirmation),cancel,board)['metrics']
                         if ranked else None)
    shortlist=[]
    for index,rank in enumerate(ranked):
        candidate=replace(candidates[rank][1],seed=validation_seed)
        row=dict(results[rank])
        row['validation']=experiment(candidate,0,sample_count(candidate,confirmation),cancel,board)['metrics']
        row['validation_value']=row['validation'][metric]
        row['validation_error']=error(row['validation_value'])
        shortlist.append(row)
        progress(dict(phase='Checking with fresh seed',done=len(candidates)+index+1,
                      total=len(candidates)+len(ranked)))
    shortlist.sort(key=lambda row:order(row,'validation_value','validation_error'))
    return dict(metric=metric,target=target,tolerance=tolerance,mode=mode,baseline=baseline,
                validation_baseline=validation_baseline,candidates=results,recommendations=shortlist,
                trials=trials,confirmation=confirmation,validation_seed=validation_seed,
                searched=len(candidates),possible=total,skipped=skipped,first_problem=first_problem,
                matched=any(row['validation_error'] is not None and row['validation_error']<=tolerance
                            for row in shortlist),settings=settings,board=board_metadata(board)['layout'])
