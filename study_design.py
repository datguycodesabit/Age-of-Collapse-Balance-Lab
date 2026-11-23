"""Validated axes and seeded candidate generation for Large Study."""
import itertools
import json
import math
import random
from collections import Counter
from dataclasses import asdict, replace

from engine import board_from, board_metadata, settings_from
from model import neighbors, path_between, zone_at

ZONES=(1,2,3)
MATCHUPS=('Fixed · lone shallow farmer','Fixed · shallow-heavy',
          'Adaptive · mixed','Adaptive · deep-heavy')
NUMERIC=sorted({
    'turns','players','start_energy','gain','cap','farm_cost','mine_cost','farm_shared_limit',
    'deep_entry_tonic','deep_tonic_energy','deep_cache_loot','full_energy_moves','boots_move_range',
    'delve','retreat','dark_cost','rough_cost','buy_boots','boots_price','sword_price','shield_price',
    'upgrade_price','shop_gold_prices','field_starter_gear','shield_block_per_level',
    'sword_damage_bonus','bow_savings','grenade_savings','use_potions','energy_potion_gain',
    'canister_gain','lose_depth','boss_enabled','boss_start','boss_threshold','boss_loot_loss','boss_energy_hit',
} | {f'{prefix}{z}' for z in ZONES for prefix in (
    'deck_monsters','deck_treasures','treasure_min','treasure_max','hp_min','hp_max','atk','bounty')})
STARTER_AXES=[
    dict(key='start_energy',values=[3,4,5]),dict(key='gain',values=[1,2,3]),
    dict(key='farm_location1',values=[0,-1,-2,1,2]),dict(key='farm_cost',values=[2,3]),
]


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'))


def layout(board):
    return board_metadata(board)['layout']


def distance(board,tile):
    return len(path_between(board.start,tile,(),board))-1


def farm_shift(board,z,delta):
    if not delta:
        return board
    old=board.primary_farm(z)
    if old is None:
        raise ValueError(f'Place a farm in Zone {z} before varying its distance.')
    target=distance(board,old)+delta
    choices=[(x,y) for x in range(6) for y in range(3*z-2,3*z+1)
             if (x,y) not in board.rocks|board.shops and (x,y) not in board.farms
             and distance(board,(x,y))==target]
    if not choices:
        raise ValueError('No farm tile at that distance.')
    tile=min(choices,key=lambda t:(len(path_between(old,t,(),board)),t))
    return board.move_farm(old,tile)


def generated_family(board,seed,count,bounds):
    """Keep each zone's site inventory while varying all three gate columns."""
    rng=random.Random(seed+434849)
    inventories={field:Counter(zone_at(t) for t in getattr(board,field))
                 for field in ('shops','mines','rocks')}
    farm_counts={z:len(board.farms_in(z)) for z in ZONES}
    tiles={z:[(x,y) for x in range(6) for y in range(10) if zone_at((x,y))==z]
           for z in range(4)}
    seen={board}
    generated=[]
    for _ in range(min(3000,count*180)):
        gates=tuple(rng.randrange(6) for _ in ZONES)
        floor=replace(board,gates=gates,shops=frozenset(),mines=frozenset(),rocks=frozenset())
        protected={t for z in ZONES for t in (floor.entrance(z),floor.exit(z-1))}
        farms=[]
        for z in ZONES:
            amount=farm_counts[z]
            if not amount:
                continue
            lo,hi=bounds[z-1]
            choices=[tile for tile in tiles[z] if lo<=distance(floor,tile)<=hi]
            if len(choices)<amount:
                break
            farms.extend([rng.choice(choices)] if amount==1 else rng.sample(choices,amount))
        if len(farms)!=len(board.farms):
            continue
        places={field:set() for field in inventories}
        for z in range(4):
            available=[t for t in tiles[z] if t not in farms]
            rng.shuffle(available)
            rock_tiles=[t for t in available if t not in protected][:inventories['rocks'][z]]
            places['rocks'].update(rock_tiles)
            available=[t for t in available if t not in rock_tiles]
            if z==0 and board.start in board.shops and inventories['shops'][z]:
                available.sort(key=lambda t:t!=floor.start)
            shops=inventories['shops'][z]
            places['shops'].update(available[:shops])
            places['mines'].update(available[shops:shops+inventories['mines'][z]])
        if any(Counter(zone_at(t) for t in places[field])!=inv for field,inv in inventories.items()):
            continue
        candidate=replace(floor,farms=tuple(sorted(farms,key=lambda tile:(tile[1],tile[0]))),
                          **{k:frozenset(v) for k,v in places.items()})
        if candidate in seen or any(not neighbors(t,(),candidate) for t in protected):
            continue
        if any(not path_between(candidate.start,t,(),candidate)
               for zone in tiles.values() for t in zone if t not in candidate.rocks):
            continue
        if any(not bounds[zone_at(tile)-1][0]<=distance(candidate,tile)<=bounds[zone_at(tile)-1][1]
               for tile in farms):
            continue
        seen.add(candidate)
        generated.append(candidate)
        if len(generated)==count:
            break
    return generated


def options_int(value,low,high,label):
    if type(value) is not int or not low<=value<=high:
        raise ValueError(f'{label} must be a whole number from {low} to {high}.')
    return value


def make_design(settings,board,spec):
    if not settings.dice_rules or not 3<=settings.players<=8 or settings.turns>30:
        raise ValueError('Large Study requires Dice rules, 3–8 seats and up to 30 rounds.')
    budget=options_int(spec.get('candidates',96),1,600,'Candidate budget')
    rotations={k:options_int(spec.get(k,default),1,limit,k.capitalize()+' rotations')
               for k,default,limit in (('screen',1,10),('refine',3,20),('fresh',10,40))}
    raw=spec.get('axes',STARTER_AXES)
    if not isinstance(raw,list) or len(raw)>12:
        raise ValueError('Choose up to 12 study axes.')
    maps=[('Current map',board)]
    boards=spec.get('maps',[])
    if not isinstance(boards,list) or len(boards)>30:
        raise ValueError('Choose up to 30 saved maps.')
    for i,definition in enumerate(boards,1):
        maps.append((f'Saved map {i}',board_from(definition)))
    family=spec.get('generate',{})
    if not isinstance(family,dict):
        raise ValueError('Invalid generated map options.')
    generated_count=options_int(family.get('count',0),0,40,'Generated maps')
    bounds=family.get('bounds',[[1,59]]*3)
    if (not isinstance(bounds,list) or len(bounds)!=3 or any(not isinstance(b,list) or len(b)!=2
            or any(type(n) is not int for n in b) or not 1<=b[0]<=b[1]<=59 for b in bounds)):
        raise ValueError('Set an ordered farm distance range from 1 to 59 for each zone.')
    maps.extend((f'Generated map {i}',value) for i,value in
                enumerate(generated_family(board,settings.seed,generated_count,bounds),1)
                if generated_count)
    if len(maps)-len(boards)-1<generated_count:
        raise ValueError('The distance ranges did not yield enough connected maps. Widen the ranges or request fewer maps.')
    axes={}
    for axis in raw:
        if not isinstance(axis,dict) or not isinstance(axis.get('key'),str):
            raise ValueError('Each axis needs a setting and values.')
        key=axis['key']
        if key in axes or key not in [*NUMERIC,*[f'{prefix}{z}' for z in ZONES
                                                  for prefix in ('farm_location','treasure_profile')]]:
            raise ValueError(f'Unknown or repeated axis: {key}.')
        values=axis.get('values')
        if values is None and key in NUMERIC:
            lo,hi,step=(axis.get(field) for field in ('min','max','step'))
            if any(type(n) is not int for n in (lo,hi,step)) or step<1 or hi<lo or (hi-lo)//step>=100:
                raise ValueError(f'Invalid min, max and step for {key}.')
            values=list(range(lo,hi+1,step))
        if not isinstance(values,list) or not 1<=len(values)<=100:
            raise ValueError(f'Enter 1–100 choices for {key}.')
        if key.startswith('treasure_profile'):
            if any(v is not None and not isinstance(v,dict) for v in values):
                raise ValueError('Treasure profiles use objects such as {"2":6,"4":6}.')
            for value in (v for v in values if v is not None):
                if (len(value)>51 or any(gold not in {str(n) for n in range(51)}
                        or type(count) is not int or not 1<=count<=50 for gold,count in value.items())
                        or sum(value.values())>50):
                    raise ValueError(f'Invalid exact card counts for {key}.')
        elif any(type(v) is not int or abs(v)>1000000 for v in values):
            raise ValueError(f'{key} needs whole-number choices.')
        axes[key]=list({canonical(v):v for v in values}.values())
    if len(maps)>1:
        if len(axes)==12:
            raise ValueError('The map family counts as one of the 12 axes.')
        axes['map_family']=list(range(len(maps)))
    if not axes:
        raise ValueError('Choose at least one study axis or map.')
    baseline=asdict(settings)
    base_layout=layout(board)
    identity={canonical([baseline,base_layout])}
    base_axes={key:('Current map' if key=='map_family' else 0 if key.startswith('farm_location')
                    else baseline['treasure_profiles'].get(key[-1],'Range') if key.startswith('treasure_profile')
                    else baseline[key]) for key in axes}
    candidates=[dict(id=0,label='Current setup',settings=baseline,board=base_layout,axes=base_axes)]
    names=list(axes)
    choices=list(axes.values())
    total=math.prod(map(len,choices))
    rng=random.Random(settings.seed+12840539)

    def vectors():
        if total<=budget:
            yield from itertools.product(*choices)
            return
        # Shuffle each column per pass so rare axis values get sampled early.
        for _ in range(max(25,min(200,budget*2))):
            columns=[rng.sample(column,len(column)) for column in choices]
            offsets=[rng.randrange(len(column)) for column in columns]
            for i in range(max(map(len,columns))):
                yield tuple(column[(i+offset)%len(column)] for offset,column in zip(offsets,columns))
        if total<=10000:
            yield from itertools.product(*choices)

    seen=set()
    rejected=0
    invalid_examples=[]
    for vector in vectors():
        if len(candidates)>budget:
            break
        digest=canonical(vector)
        if digest in seen:
            continue
        seen.add(digest)
        dimensions=dict(zip(names,vector))
        map_name,candidate_board=maps[dimensions.get('map_family',0)]
        config=dict(baseline,treasure_profiles=baseline['treasure_profiles'].copy())
        try:
            for key,value in dimensions.items():
                if key.startswith('farm_location'):
                    candidate_board=farm_shift(candidate_board,int(key[-1]),value)
                elif key.startswith('treasure_profile'):
                    if value is None:
                        config['treasure_profiles'].pop(key[-1],None)
                    else:
                        config['treasure_profiles'][key[-1]]=value
                        if f'deck_treasures{key[-1]}' not in dimensions:
                            config[f'deck_treasures{key[-1]}']=sum(value.values())
                elif key!='map_family':
                    config[key]=value
            for zone in ZONES:
                profile=config['treasure_profiles'].get(str(zone))
                if profile is not None and config[f'deck_treasures{zone}']!=sum(profile.values()):
                    raise ValueError(f'Zone {zone} exact-value counts conflict with its Treasure count axis.')
            if 'turns' in dimensions:
                for field in ('retreat_start','zone2_start','zone3_start'):
                    if field not in dimensions:
                        config[field]=min(config[field],config['turns']+1)
            candidate=settings_from(config)
            if not 3<=candidate.players<=8 or candidate.turns>30:
                raise ValueError('Study candidates require 3–8 seats and at most 30 rounds.')
        except ValueError as exc:
            rejected+=1
            if str(exc) not in invalid_examples and len(invalid_examples)<5:
                invalid_examples.append(str(exc))
            continue
        candidate_layout=layout(candidate_board)
        signature=canonical([config,candidate_layout])
        if signature in identity:
            continue
        identity.add(signature)
        if 'map_family' in dimensions:
            dimensions['map_family']=map_name
        number=len(candidates)
        candidates.append(dict(id=number,label=f'Setup {number}',settings=config,board=candidate_layout,axes=dimensions))
    if len(candidates)==1:
        raise ValueError('No legal variants differ from the current setup. '+' '.join(invalid_examples))
    seats=max(c['settings']['players'] for c in candidates)
    screen_count=len(candidates)
    refine_count=1+min(12,screen_count-1)
    fresh_count=1+min(6,screen_count-1)
    # Each route can evaluate eight alternatives and the rolling incumbent.
    upper=4*seats*(screen_count*rotations['screen']+
                    refine_count*(2*rotations['refine']+3*9)+fresh_count*rotations['fresh']*2)
    if upper>250000:
        raise ValueError('The study exceeds 250,000 matches. Reduce the candidate budget or rotations.')
    return dict(version=1,axes=names,candidates=candidates,rotations=rotations,grid=str(total),
                rejected=rejected,warnings=invalid_examples,generated=generated_count,
                maximum_matches=upper,seed=settings.seed)


def assignment(seats,scenario,game):
    extras=((2,3),(1,1,2),(1,2,3),(3,3,2))[scenario]
    roles=(1,2,3)+tuple(extras[i%len(extras)] for i in range(seats-3))
    offset=game%seats
    return roles[offset:]+roles[:offset],(-offset)%seats
