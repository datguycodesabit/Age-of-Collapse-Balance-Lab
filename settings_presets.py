"""Matched searches for common dice balance questions."""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, replace
from statistics import mean, stdev

from balance_study import LINEUPS, play, summarize_routes
from dice_rules import deck_composition
from engine import board_metadata, settings_from
from model import path_between, zone_at
from tune_shop import SEED_STRIDE
from tune_turn_length import Timing, percentile


# The variant description and ranking criteria are also displayed in the lab.
CATALOG = {
    'opening': ('Opening Energy', '2, 3, 4 and 5 opening Energy.',
                'Favor deeper mining and banking while keeping the shallow score in the middle.'),
    'refill': ('Round refill', '1, 2, 3 and 4 Energy per subsequent round.',
               'Protect deeper banking and shallow farm activity.'),
    'farm1': ('Zone 1 farm location', 'Move the farm one or two steps, with options toward and away from Surface.',
              'Keep the shallow farm active and its mean score between the deeper routes.'),
    'farm2': ('Zone 2 farm vs. nearby mines', 'Move the farm, swap it with a mine, or move a nearby regular mine.',
              'Favor a credible Zone 2 mean and actual use of both kinds of site.'),
    'farm3': ('Zone 3 farm distance', 'Test legal farm tiles nearest to 20, 22 and 24 steps from Surface.',
              'Favor deep banking and preserve a high winning payoff.'),
    'farm_cost': ('Farm Energy cost', '2 versus 3 Energy per Farm. Mine cost stays fixed.',
                  'Reward regular mine use while protecting shallow farm activity.'),
    'farm_sharing': ('Farm access under crowding', 'Unlimited, one or two shared farm activations per site per round.',
                     'Favor mining across sites in crowded games while protecting deeper banking.'),
    'treasure1': ('Shallow treasure ceiling', 'Zone 1 treasure ranges of 1–3, 1–4, 2–4, 2–5 and 1–5.',
                  'Favor the shallow score falling between the Zone 2 and Zone 3 means.'),
    'treasure2': ('Zone 2 reward consistency', 'Narrow or widen Zone 2 values, or swap two Nothing / Treasure cards.',
                  'Favor tighter Zone 2 scores with viable mining and banking.'),
    'treasure3': ('Zone 3 winning upside', 'Cache off. Compare 7–11, 8–12, 8–14 and 9–13 treasures.',
                  'Favor larger deep wins while penalizing very low or excessive deep win rates.'),
    'decks': ('Deck reserves', 'Swap two Treasures with Nothing or Monster cards in one zone at a time. Decks stay at 50 cards.',
              'Favor a five-card reserve at the 95th draw percentile in each zone.'),
    'combat': ('Monster HP vs. attack', 'Raise or lower Zone 2–3 HP or Attack separately, by one.',
               'Favor fewer knockdowns and combat Energy losses while preserving depth incentives.'),
    'bounty': ('Monster bounty', 'Raise or lower Zone 2 or Zone 3 bounties by one gold.',
               'Favor Zone 2 and 3 banking and balanced win chances.'),
    'boots': ('Boots price and reach', 'Vary Boots price (1, 2, 3) and reach (3, 4, 5) one at a time.',
              'Favor useful purchases, reasonable spend, and better deep banking.'),
    'arms': ('Sword vs. Shield value', 'Vary Sword or Shield price and strength, one setting at a time.',
             'Favor fewer knockdowns and useful gear while penalizing one item crowding out the other.'),
    'shops': ('Underground shop placement', 'Move one underground shop up to two open steps toward a farm or a gate.',
              'Favor useful purchases and better banking from Zones 2 and 3.'),
    'tonic': ('Zone 3 entrance tonic', 'Entrance tonic off, +2 Energy, or +3 Energy.',
              'Favor mining and returning to bank from Zone 3.'),
    'boss': ('Boss pressure', 'Vary boss arrival, fixed collapse threshold, or moving boss HP.',
             'Favor fewer forced ejections while retaining meaningful collapse pressure.'),
    'rounds': ('Round limit and table time', 'Compare 14, 15 and 16 rounds. Use the tabletop action-time estimates.',
               'Favor shorter matches with enough time to mine deep, bank and finish on Surface.'),
    'seats': ('Table-size resilience', 'Match three, four, five and six seats at the same rules and map.',
              'Favor balanced split-win chances across routes, deeper banking, and deck reserves.'),
}


def ranges(zone, bounds):
    return [{f'treasure_min{zone}':low, f'treasure_max{zone}':high} for low,high in bounds]


def numeric_variants(key,s):
    if key=='opening':
        return [{'start_energy':n} for n in range(2,6)]
    if key=='refill':
        return [{'gain':n} for n in range(1,5)]
    if key=='farm_cost':
        return [{'farm_cost':n} for n in (2,3)]
    if key=='farm_sharing':
        return [{'farm_shared_limit':n} for n in (0,1,2)]
    if key=='treasure1':
        return ranges(1,[(1,3),(1,4),(2,4),(2,5),(1,5)])
    if key=='treasure2':
        return ranges(2,[(3,5),(2,6),(1,7)])+[
            {'deck_treasures2':s.deck_treasures2+delta} for delta in (-2,2)]
    if key=='treasure3':
        return [dict(changes,deep_cache_loot=0) for changes in
                ranges(3,[(7,11),(8,12),(8,14),(9,13)])]
    if key=='decks':
        return [
            {f'deck_treasures{zone}':getattr(s,f'deck_treasures{zone}')+delta,
             **({f'deck_monsters{zone}':getattr(s,f'deck_monsters{zone}')-delta}
                if monster_swap else {})}
            for zone in (1,2,3) for delta in (-2,2) for monster_swap in (False,True)]
    if key=='combat':
        if s.rolled_enemy_attacks:
            trials = []
            for zone in ('2','3'):
                for delta in (-1, 1):
                    profiles = deepcopy(s.monster_profiles)
                    for profile in profiles[zone].values():
                        profile['hp'] = max(1, profile['hp'] + delta)
                    trials.append(dict(monster_profiles=profiles))
                    profiles = deepcopy(s.monster_profiles)
                    for profile in profiles[zone].values():
                        profile['faces'] = [max(0, min(20, hit + delta)) for hit in profile['faces']]
                    trials.append(dict(monster_profiles=profiles))
            return trials
        return [
            {f'hp_min{zone}':max(1,getattr(s,f'hp_min{zone}')+delta),
             f'hp_max{zone}':getattr(s,f'hp_max{zone}')+delta}
            for zone in (2,3) for delta in (-1,1)
        ]+[{f'atk{zone}':getattr(s,f'atk{zone}')+delta}
           for zone in (2,3) for delta in (-1,1)]
    if key=='bounty':
        return [{f'bounty{zone}':getattr(s,f'bounty{zone}')+delta}
                for zone in (2,3) for delta in (-1,1)]
    if key=='boots':
        return [{'boots_price':n} for n in (1,2,3)]+[{'boots_move_range':n} for n in (3,4,5)]
    if key=='arms':
        fields = (
            ('sword_price',(1,2,3)),('shield_price',(1,2,3)),
            ('sword_damage_bonus',(0,1,2)),('shield_block_per_level',(1,2)))
        return [{field:n} for field,values in fields if not s.rolled_enemy_attacks
                or field != 'shield_block_per_level' for n in values]
    if key=='tonic':
        return [{'deep_entry_tonic':0}]+[
            {'deep_entry_tonic':1,'deep_tonic_energy':n} for n in (2,3)]
    if key=='boss':
        if s.moving_boss:
            return [dict(boss_enabled=1,**{field:getattr(s,field)+delta})
                    for field, deltas in (('boss_start', (-1, 1)), ('boss_hp', (-4, 4)))
                    for delta in deltas]
        return [
            dict(boss_enabled=1,**{field:getattr(s,field)+delta})
            for field in ('boss_start','boss_threshold') for delta in (-1,0,1)]
    if key=='rounds':
        return [{'turns':n,'retreat_start':min(s.retreat_start,n+1)} for n in (14,15,16)]
    if key=='seats':
        return [{'players':n} for n in (3,4,5,6)]
    return []


def map_variants(key,board):
    def distance(a,b):
        return len(path_between(a,b,(),board))-1

    def empty(zone):
        return [(x,y) for y in range(3*zone-2,3*zone+1) for x in range(6)
                if (x,y) not in blocked]

    def relocate_farm(zone,tile):
        old=board.primary_farm(zone)
        label=f'Zone {zone} farm {distance(tile,board.start)} steps from Surface'
        if tile in board.mines:
            label+=', swap with mine'
        return label,board.move_farm(old,tile)

    blocked=board.shops|board.rocks|board.mines|set(board.farms)
    if key in ('farm1','farm2'):
        zone=int(key[-1])
        farm=board.primary_farm(zone)
        if farm is None:
            return
        near=[tile for tile in empty(zone) if distance(tile,farm)<=2]
        if key=='farm1':
            for steps in sorted({distance(tile,board.start) for tile in near}):
                tile=min((t for t in near if distance(t,board.start)==steps),
                         key=lambda t:(distance(t,farm),t))
                yield relocate_farm(zone,tile)
        else:
            mines=sorted(tile for tile in board.mines if zone_at(tile)==zone)
            for tile in mines:
                yield relocate_farm(zone,tile)
            for tile in sorted(near,key=lambda t:(distance(t,farm),t))[:2]:
                yield relocate_farm(zone,tile)
            for mine in mines[:2]:
                for tile in sorted(empty(zone),key=lambda t:(distance(t,farm),t)):
                    if distance(mine,tile)<=2:
                        yield ('Zone 2 mine nearer the farm',
                               replace(board,mines=(board.mines-{mine})|{tile}))
                        break
    elif key=='farm3':
        farm=board.primary_farm(3)
        if farm is None:
            return
        tiles=[farm]+empty(3)+[tile for tile in sorted(board.mines) if zone_at(tile)==3]
        for target in (20,22,24):
            tile=min(tiles,key=lambda t:(abs(distance(t,board.start)-target),distance(t,farm),t))
            if tile!=farm:
                yield relocate_farm(3,tile)
    elif key=='shops':
        for shop in sorted(board.shops):
            zone=zone_at(shop)
            if not zone:
                continue
            nearby=[t for t in empty(zone) if distance(t,shop)<=2]
            for goal,label in ((board.primary_farm(zone),'farm'),(board.entrance(zone),'gate')):
                if goal is None:
                    continue
                closer=[t for t in nearby if distance(t,goal)<distance(shop,goal)]
                if closer:
                    tile=min(closer,key=lambda t:(distance(t,goal),distance(t,shop),t))
                    yield (f'Zone {zone} shop toward {label}',
                           replace(board,shops=(board.shops-{shop})|{tile}))


def variants(key,s,board):
    base=asdict(s)
    layout=board_metadata(board)['layout']
    output=[dict(label='Current setup',changes={},board=layout)]
    seen={board}
    for label,candidate in map_variants(key,board):
        if candidate not in seen:
            seen.add(candidate)
            output.append(dict(label=label,changes={},board=board_metadata(candidate)['layout']))
    for trial in numeric_variants(key,s):
        changes={k:v for k,v in trial.items() if base[k]!=v}
        if not changes or any(row['changes']==changes for row in output):
            continue
        try:
            settings_from(dict(base,**changes))
        except ValueError:
            # Custom baselines may have no room for another card or a lower HP.
            continue
        label = 'Rule change'
        if 'monster_profiles' in changes:
            for zone, group in changes['monster_profiles'].items():
                before = s.monster_profiles[zone]['Balanced']
                after = group['Balanced']
                if before != after:
                    field = 'HP' if before['hp'] != after['hp'] else 'counterattack'
                    label = f'Zone {zone} {field} {"raised" if after["hp"] > before["hp"] or sum(after["faces"]) > sum(before["faces"]) else "lowered"}'
                    break
        output.append(dict(label=label,changes=changes,board=layout))
    return output


def match_metrics(match):
    timing=Timing()
    turn_times={}
    actions=defaultdict(list)
    for command in match.journal:
        actions[command['actor']].append(command['action'])
    for seat,rows in enumerate(match.logs):
        real_actions=[row for row in rows if not row['boss_roll']
                      and row['action'] not in ('Defend duel', 'Boss defeated')]
        if len(real_actions)!=len(actions[seat]):
            raise RuntimeError('Timing requires one action row per accepted command.')
        for action,row in zip(actions[seat],real_actions):
            turn=(seat,row['turn'])
            turn_times[turn]=turn_times.get(turn,timing.turn_start)+timing.action_seconds(action,row)
    shared_time=sum(timing.boss_roll+(timing.collapse if event['collapse'] else 0)
                    for event in match.boss_events)
    rows=[row for log in match.logs for row in log]
    purchases=[row for row in rows if row['action'].startswith('Buy ')]
    exchanges=[exchange for row in rows for combat in row.get('combat_events',())
               for exchange in combat['exchanges']]
    exchanges.extend(exchange for row in rows if row['action'] == 'Challenge'
                     for exchange in row['duel']['exchanges'])
    return dict(draws=[50-len(match.decks[z]) for z in (1,2,3)], turn_times=list(turn_times.values()),
                minutes=(sum(turn_times.values())+shared_time)/60,
                knockdowns=sum(row['knockdown']=='Yes' for row in rows),
                combat_energy=sum(row['combat_cost'] for row in rows),
                ejections=sum(row['boss_ejection'] for row in rows),
                collapsed=bool(match.closed), spend=sum(r['loot_spent']+r.get('bank_spent',0) for r in purchases),
                farm=sum(row['action']=='Farm' for row in rows),
                shallow_farm=sum(row['action']=='Farm' and row['farm_zone']==1 for row in rows),
                long_boot_moves=sum('Boots' in row['equipment'] and row.get('move_steps',0)
                                    > 2*(1+('Haste Potion' in row['potions_used'])) for row in rows),
                sword_damage=sum(exchange['weapon'] for exchange in exchanges),
                shield_block=sum(exchange['shield_absorbed'] for exchange in exchanges),
                mines=[sum(row['action']=='Mine' and row['farm_zone']==z for row in rows)
                       for z in (1,2,3)],
                buyers={item:sum(any(row['action']=='Buy '+item for row in log) for log in match.logs)
                        for item in ('Boots','Sword','Shield')})


def summarize(matches,details,seats):
    routes=summarize_routes(matches)
    players=[p for m in matches for depth in (1,2,3) for p in m[depth]]
    return dict(routes=routes, actual_mined=[mean(z in p['mined_zones'] for p in players) for z in (1,2,3)],
                score_spread2=stdev([p['score'] for m in matches for p in m[2]]),
                p95_draws=[percentile([row['draws'][i] for row in details],.95) for i in range(3)],
                depleted=[mean(row['draws'][i]==50 for row in details) for i in range(3)],
                minutes=mean(row['minutes'] for row in details),
                p95_turn=percentile([t for row in details for t in row['turn_times']],.95),
                collapse=mean(row['collapsed'] for row in details),
                **{name:mean(row[name] for row in details)/seats
                   for name in ('knockdowns','combat_energy','ejections','farm','shallow_farm','spend',
                                'long_boot_moves','sword_damage','shield_block')},
                mines=[mean(row['mines'][i] for row in details)/seats for i in range(3)],
                buyers={item:mean(row['buyers'][item] for row in details)/seats
                        for item in ('Boots','Sword','Shield')})


def penalty(key,scenarios,seats):
    # The fixed policies supply comparable target-route scores. The adaptive
    # policies supply observed depth and site mix when bots can change plans.
    fixed=[r for r in scenarios if not r['adaptive']]
    adaptive=[r for r in scenarios if r['adaptive']]
    middle=mean(max(0,min(b,c)-a,a-max(b,c))/max(1,mean((a,b,c)))
                for row in fixed for a,b,c in [[r['score'] for r in row['routes']]])
    mine=mean(row['actual_mined'][2] for row in adaptive)
    bank=mean(row['routes'][2]['funnel']['banked']['rate'] for row in fixed)
    bank2=mean(row['routes'][1]['funnel']['banked']['rate'] for row in fixed)
    short=mean(max(0,1-row['shallow_farm']) for row in fixed)
    balance=mean(sum(abs(r['win']-1/seats) for r in row['routes']) for row in fixed)
    deep_win=mean(row['routes'][2]['win'] for row in fixed)
    upside=mean((row['routes'][2]['winning_score'] or 0) for row in fixed)/40
    reserve=mean(sum(max(0,n-45)/15 for n in row['p95_draws']) for row in scenarios)
    regular=mean(sum(row['mines']) for row in adaptive)
    mine2=mean(min(row['mines'][1],1) for row in adaptive)
    gear={item:mean(row['buyers'][item] for row in adaptive) for item in ('Boots','Sword','Shield')}
    knock=mean(row['knockdowns'] for row in scenarios)
    common=middle+.35*(1-bank)+.10*balance
    targeted={
        'opening': .6*(1-mine)+.6*(1-bank),
        'refill': .65*(1-bank)+.25*short,
        'farm1': middle+.5*short,
        'farm2': .6*(1-bank2)+.25*(1-mine2),
        'farm3': .75*(1-bank)-.3*upside,
        'farm_cost': .35*short-.25*min(regular,2),
        'farm_sharing': .55*(1-adaptive[-1]['actual_mined'][2])-.2*min(regular,2),
        'treasure1': 2*middle+.1*short,
        'treasure2': mean(row['score_spread2'] for row in fixed)/40+.65*(1-bank2),
        'treasure3': -.55*upside+1.5*max(0,.08-deep_win,deep_win-.23),
        'decks': 2*reserve+.35*(1-mine),
        'combat': .4*knock+mean(row['combat_energy'] for row in scenarios)/60,
        'bounty': .5*(1-bank)+.4*(1-bank2)+.35*balance,
        'boots': .55*(1-bank)-.35*gear['Boots']
                 +mean(row['spend']-min(row['long_boot_moves'],5) for row in adaptive)/60,
        'arms': .55*knock-.3*min(gear['Sword'],gear['Shield'])+.25*abs(gear['Sword']-gear['Shield']),
        'shops': .5*(1-bank)+.5*(1-bank2)-.15*sum(gear.values()),
        'tonic': .65*(1-bank)+.55*(1-mine),
        'boss': mean(.35*row['ejections']+.35*max(0,.5-row['collapse']) for row in scenarios),
        'rounds': mean(row['minutes'] for row in scenarios)/85
                  +max(0,.65-bank)+.5*(1-bank2),
        'seats': .6*balance+reserve+.55*(1-bank),
    }
    return common+targeted[key]


def run_preset(settings,spec,board,progress=None,cancel=None):
    key=spec.get('preset')
    if not isinstance(key,str) or key not in CATALOG:
        raise ValueError('Choose a settings search preset.')
    screening,holdout=spec.get('screening',6),spec.get('holdout',12)
    if (type(screening) is not int or not 3<=screening<=40
            or type(holdout) is not int or not 3<=holdout<=80):
        raise ValueError('Choose 3–40 screening and 3–80 fresh games per matchup.')
    if not settings.dice_rules or not 3<=settings.players<=8 or settings.turns>30:
        raise ValueError('Preset searches use Dice rules, 3–8 seats and up to 30 rounds.')
    requirements={'boots':settings.full_energy_moves and settings.buy_boots,
                  'tonic':settings.use_potions}
    if key in requirements and not requirements[key]:
        raise ValueError('Enable Boots and 1-Energy movement, or allow potion use for the tonic search.')
    candidates=variants(key,settings,board)
    if len(candidates)<2:
        raise ValueError('This setup has no legal variants for the selected search.')
    finalist_count=min(3,len(candidates)-1)
    total=4*(len(candidates)*screening+(finalist_count+1)*holdout)
    completed=0
    base=asdict(settings)
    fresh=(settings.seed+104729*SEED_STRIDE+21701)%(2**53)

    def measure(candidate,games,seed,phase):
        nonlocal completed
        config=dict(base,**candidate['changes'])
        scenarios=[]
        for rotating,name in enumerate(LINEUPS):
            for adaptive in (False,True):
                matches=[]
                details=[]
                for game in range(games):
                    trial=(seed+game*SEED_STRIDE)%(2**53)
                    matches.append(play(config,candidate['board'],trial,game,rotating,adaptive,
                                        Counter(),[],cancel,lambda m: details.append(match_metrics(m))))
                    completed+=1
                    if progress:
                        progress(dict(phase=f'{phase} · {name}',done=completed,total=total))
                scenarios.append(dict(label=name,adaptive=adaptive,
                                      **summarize(matches,details,config['players'])))
        return dict(penalty=penalty(key,scenarios,config['players']),scenarios=scenarios)

    for candidate in candidates:
        candidate['screening']=measure(candidate,screening,settings.seed,'Screening')
    finalists=sorted(candidates[1:],key=lambda row:row['screening']['penalty'])[:finalist_count]
    baseline=candidates[0]
    for candidate in [baseline,*finalists]:
        candidate['holdout']=measure(candidate,holdout,fresh,'Fresh-seed check')
    finalists.sort(key=lambda row:row['holdout']['penalty'])
    return dict(preset=key,settings=base,screening_games=screening,holdout_games=holdout,
                screened=len(candidates),validation_seed=fresh,baseline=baseline,finalists=finalists,
                screening=[dict(label=row['label'],changes=row['changes'],board=row['board'],
                                penalty=row['screening']['penalty']) for row in candidates])
