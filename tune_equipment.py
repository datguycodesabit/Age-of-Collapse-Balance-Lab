"""Search gear prices and validate the finalist on an independent seed."""
import argparse
import json
import random
import statistics
from dataclasses import replace

from engine import experiment
from model import GEAR, Settings


def assess(settings, players):
    result = experiment(settings, sample_limit=0, player_count=players)
    rates = result['equipment_rates']
    usage = [item['used_percent'] for item in rates]
    metrics = result['metrics']
    return {
        'items': rates,
        'spread': max(usage)-min(usage),
        'mean_use': statistics.mean(usage),
        'use_sd': statistics.pstdev(usage),
        'voluntary_escape': metrics['voluntary_escape_rate'],
        'avg_score': metrics['avg_score'],
        'zone3_rate': metrics['zone3_rate'],
    }


def tune(players, confirmation, seed):
    settings = Settings(seed=seed, gear_priority=4)
    keys = [price for price, _ in GEAR.values()]
    original = {key:getattr(settings,key) for key in keys}
    baseline = assess(settings, players)

    def objective(result):
        return (
            result['spread'] + .5*result['use_sd']
            + 4*max(0,20-result['mean_use'])
            + 5*max(0,baseline['voluntary_escape']-5-result['voluntary_escape'])
            + 6*max(0,baseline['avg_score']-2-result['avg_score'])
        )

    seen = {tuple(original.values()): objective(baseline)}

    def evaluate(prices):
        if prices not in seen:
            seen[prices]=objective(assess(replace(settings,**dict(zip(keys,prices))),players))
        return seen[prices]

    rng=random.Random(seed+5587)
    starts=[tuple(original.values()),(4,4,2,3,3,4,2,4,3,2),(3,3,2,2,2,3,2,3,3,2)]
    for prices in starts:
        score=evaluate(prices)
        for index in range(54):
            trial=list(prices)
            for position in rng.sample(range(len(keys)),1 if index%3 else 2):
                trial[position]=max(1,min(14,trial[position]+rng.choice((-2,-1,1,2))))
            trial=tuple(trial)
            candidate=evaluate(trial)
            if candidate<score or (index<24 and candidate<score+2 and rng.random()<.15):
                prices,score=trial,candidate

    best=min(seen,key=seen.get)
    prices=dict(zip(keys,best))

    independent = replace(settings,seed=seed+9973)
    return {
        'prices': prices, 'original_prices': original, 'candidate_runs': len(seen),
        'search_seed': seed, 'confirmation_seed': independent.seed,
        'players_per_candidate': players, 'players_per_confirmation': confirmation,
        'original': assess(independent,confirmation),
        'tuned': assess(replace(independent,**prices),confirmation),
        'fixed_order': assess(replace(independent,gear_priority=0),confirmation),
    }


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--players',type=int,default=240)
    parser.add_argument('--confirmation',type=int,default=4000)
    parser.add_argument('--seed',type=int,default=20261117)
    args=parser.parse_args()
    print(json.dumps(tune(args.players,args.confirmation,args.seed),indent=2))
