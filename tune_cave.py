"""Seeded balance search for two boards and three expedition policies."""
import argparse
import json
import random
import statistics
import sys
from dataclasses import replace

from engine import ESCAPE_TEST_SETUP, GEAR_BALANCE_PRICES, board_from, board_metadata, experiment
from ev_audit import audit
from model import DEFAULT_BOARD, GEAR, Settings

POLICIES = {
    'Mining': dict(route_policy=1, max_zone=2, gear_priority=1),
    'Gear': dict(route_policy=2, max_zone=3, gear_priority=4),
    'Deep': dict(route_policy=3, max_zone=3, gear_priority=2),
}
BOARDS = {'Tested snake': board_from(ESCAPE_TEST_SETUP['board']), 'Original snake': DEFAULT_BOARD}
PRICE_KEYS = tuple(price for price, _ in GEAR.values())
EFFECTS = {'blade_savings': (1, 3), 'pack_protection': (1, 3), 'charm_bonus': (0, 2), 'battery_gain': (0, 2)}
BASE = Settings(**ESCAPE_TEST_SETUP['settings'])
# Starting point from the first screening pass, before adding price-aware
# preferences to each route policy.
FIRST_PASS = dict(boots_price=5, flashlight_price=5, climbing_price=4, pick_price=3, pack_price=4,
                  blade_price=1, charm_price=1, battery_price=5, map_price=4, harness_price=1,
                  p_treasure=40, p_monster=20, p_enhance=10)


def assess(settings, board, players):
    result = experiment(settings, sample_limit=0, player_count=players, board=board)
    m = result['metrics']
    keys = ('escape_rate', 'avg_score', 'avg_score_survivors', 'zone3_rate', 'cache_claim_rate',
            'boss_death_rate', 'avg_mine_actions', 'avg_farm_actions', 'card_counts', 'empty_draws')
    return {**{key: m[key] for key in keys}, 'equipment': {
        item['label']: [item['percent'], item['used_percent']] for item in result['equipment_rates']
    }}


def trials(changes, seeds, players):
    return [
        dict(seed=seed, map=label, policy=policy,
             **assess(replace(BASE, **changes, **overrides, seed=seed), board, players))
        for seed in seeds for label, board in BOARDS.items() for policy, overrides in POLICIES.items()
    ]


def summary(rows):
    policies = {policy: [row for row in rows if row['policy']==policy] for policy in POLICIES}
    scores = {policy: statistics.mean(row['avg_score'] for row in group) for policy, group in policies.items()}
    survivor = {policy: statistics.mean(row['avg_score_survivors'] or 0 for row in group) for policy, group in policies.items()}
    ratio = min(scores.values())/max(scores.values()) if max(scores.values()) else 0
    deep_lead = survivor['Deep']-max(survivor['Mining'],survivor['Gear'])
    use = {item:statistics.mean(row['equipment'][item][1] for row in rows) for item in GEAR}
    own = {item:statistics.mean(row['equipment'][item][0] for row in rows) for item in GEAR}
    cards = {card:sum(row['card_counts'][card] for row in rows) for card in rows[0]['card_counts']}
    draws = sum(cards.values())
    return dict(scores=scores,survivor_scores=survivor,viability_ratio=ratio,deep_lead=deep_lead,
                escape=statistics.mean(row['escape_rate'] for row in rows),
                escape_by_policy={policy:statistics.mean(row['escape_rate'] for row in group) for policy,group in policies.items()},
                gear_use=use,gear_owned=own,gear_spread=max(use.values())-min(use.values()),
                card_rates={card:100*count/draws if draws else 0 for card,count in cards.items()},
                empty_rate=100*sum(row['empty_draws'] for row in rows)/draws if draws else 0)


def rank(result):
    distance=abs(75-result['escape'])
    return (round(max(0,.85-result['viability_ratio'])+max(0,.01-result['deep_lead'])/20, 3),
            round(max(0,distance-3),1),result['gear_spread']-2*min(result['gear_use'].values()),distance)


def tune(seed, screening, confirmation):
    rng = random.Random(seed+197)
    tested = {}
    def evaluate(changes):
        key = tuple(sorted(changes.items()))
        if key not in tested:
            tested[key] = summary(trials(changes,[seed],screening))
        return tested[key]
    original = {key:getattr(BASE,key) for key in PRICE_KEYS}
    original.update(p_treasure=BASE.p_treasure,p_monster=BASE.p_monster,p_enhance=BASE.p_enhance)
    evaluate(original)
    evaluate(FIRST_PASS)
    for index in range(82):
        nothing = 10+5*(index%7)
        if index<20:
            candidate={**original,**(GEAR_BALANCE_PRICES if index%2 else {})}
        else:
            candidate=dict(min(tested,key=lambda key:rank(tested[key])))
        for key in rng.sample(PRICE_KEYS, rng.choice((2,3,5))):
            candidate[key]=min(10,max(1,candidate[key]+rng.choice((-2,-1,1,2))))
        treasure=rng.choice((20,25,30,35,40))
        monster=rng.choice((15,20,25,30))
        if treasure+monster+nothing>95:
            monster=max(10,95-treasure-nothing)
        candidate.update(p_treasure=treasure,p_monster=monster,p_enhance=100-nothing-treasure-monster)
        evaluate(candidate)
        if index%10==9:
            print(f'Screening {index+1}/82',file=sys.stderr,flush=True)
    for key in sorted(tested,key=lambda entry:rank(tested[entry]))[:3]:
        leader=dict(key)
        use=tested[key]['gear_use']
        for item in GEAR:
            price=GEAR[item][0]
            direction=-1 if use[item]<statistics.median(use.values()) else 1
            candidate={**leader,price:min(10,max(1,leader[price]+direction*2))}
            evaluate(candidate)
    # Look for persistent underuse or overuse before testing small effects.
    leaders=sorted(tested,key=lambda key:rank(tested[key]))[:3]
    for key in leaders:
        gear=list(tested[key]['gear_use'].values())
        if min(gear)<5 or max(gear)-min(gear)>15:
            for effect,(low,high) in EFFECTS.items():
                for value in (low,high):
                    evaluate({**dict(key),effect:value})
    confirmed=[]
    holdouts=(seed+9973,seed+19997)
    finalists=sorted(tested,key=lambda key:rank(tested[key]))[:3]
    for label,changes in [('Baseline',original),*((f'Finalist {i}',dict(key)) for i,key in enumerate(finalists,1))]:
        print(f'Confirming {label} on two fresh seeds',file=sys.stderr,flush=True)
        rows=trials(changes,holdouts,confirmation)
        confirmed.append(dict(label=label,settings=changes,summary=summary(rows),trials=rows))
    return publish(confirmed,seed,holdouts,screening,confirmation,len(tested))


def refine(previous, screening, confirmation):
    """Check cache payout and specialize the gear tradeoff on a new seed."""
    seed=previous['holdout_seeds'][-1]+10009
    selected=next(row for row in previous['confirmation'] if row['label']==previous['selected'])
    base=selected['settings']
    candidates=[]
    for loot in (6,8,10,12):
        for prices in ({},{'pack_price':base['pack_price']+1,
                           'blade_price':max(1,base['blade_price']-1),
                           'harness_price':max(1,base['harness_price']-1)}):
            changes={**base,**prices,'deep_cache_loot':loot}
            print(f'Screening cache {loot} with {"adjusted" if prices else "current"} prices',
                  file=sys.stderr,flush=True)
            candidates.append((changes,summary(trials(changes,[seed],screening))))
    finalists=sorted(candidates,key=lambda row:rank(row[1]))[:3]
    holdouts=(seed+9973,seed+19997)
    baseline=next(row['settings'] for row in previous['confirmation'] if row['label']=='Baseline')
    confirmed=[]
    for label,changes in [('Baseline',baseline),*((f'Refined {i}',row[0]) for i,row in enumerate(finalists,1))]:
        print(f'Confirming {label} on two fresh seeds',file=sys.stderr,flush=True)
        rows=trials(changes,holdouts,confirmation)
        confirmed.append(dict(label=label,settings=changes,summary=summary(rows),trials=rows))
    return publish(confirmed,seed,holdouts,screening,confirmation,previous['screened']+len(candidates))


def publish(confirmed, seed, holdouts, screening, confirmation, screened):
    selected=min(confirmed,key=lambda row:rank(row['summary']))
    settings=selected['settings']
    map_name=min(BOARDS,key=lambda name:rank(summary([row for row in selected['trials'] if row['map']==name])))
    board=BOARDS[map_name]
    print(f'Auditing mining and gear on {map_name}',file=sys.stderr,flush=True)
    late={}
    ablation={}
    action_ev={}
    for policy,overrides in POLICIES.items():
        print(f'Auditing {policy.lower()} policy',file=sys.stderr,flush=True)
        current=replace(BASE,**settings,**overrides,seed=holdouts[-1])
        normal=assess(current,board,confirmation)
        late[policy]=assess(replace(current,adaptive_retreat=0,retreat_start=current.turns-1),board,confirmation)
        report=audit(current,{'games':max(12,confirmation//current.players)},lambda _:None,lambda:False,board)
        action_ev[policy]=[row for row in report['rows'] if 'farm ·' in row['label'] or 'mine ·' in row['label']]
        ablation[policy]={}
        for item,(_,switch) in GEAR.items():
            without=assess(replace(current,**{switch:0}),board,confirmation)
            ablation[policy][item]=dict(loot_delta=normal['avg_score']-without['avg_score'],
                                        escape_delta=normal['escape_rate']-without['escape_rate'])
    return dict(screened=screened,screen_seed=seed,holdout_seeds=holdouts,
                screening_players=screening,confirmation_players=confirmation,
                preset_board=board_metadata(board)['layout'],preset_map=map_name,policies=POLICIES,
                selected=selected['label'],preset={**ESCAPE_TEST_SETUP['settings'],**settings,**POLICIES['Deep']},
                confirmation=confirmed,late_retreat=late,mining_ev=action_ev,item_ablation=ablation)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,default=20301847)
    parser.add_argument('--screening',type=int,default=100)
    parser.add_argument('--confirmation',type=int,default=1000)
    parser.add_argument('--refine',type=argparse.FileType('r'),
                        help='Refine a previous JSON report on new seeds.')
    args=parser.parse_args()
    if not 4<=args.screening<=args.confirmation<=2000:
        parser.error('Use 4–2,000 players per condition, with confirmation at least as large as screening.')
    if args.refine:
        result=refine(json.load(args.refine),args.screening,args.confirmation)
    else:
        result=tune(args.seed,args.screening,args.confirmation)
    print(json.dumps(result,indent=2))
