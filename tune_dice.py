"""Matched-seat balance study for the dice ruleset. Prints JSON to stdout."""
from collections import defaultdict
import json
from statistics import mean

from engine import settings_from, shared_game
from model import DEFAULT_BOARD

TRAIN_SEED = 957231
HOLDOUT_SEED = 1942001
LINEUP = (1, 1, 2, 3)
BASELINE = dict(hp_min1=2,hp_max1=4,hp_min2=4,hp_max2=6,hp_min3=6,hp_max3=9,
                sword_price=2,shield_price=2,upgrade_price=2,treasure_min1=1,treasure_max1=3,
                treasure_min2=2,treasure_max2=5,treasure_min3=3,treasure_max3=7,
                deck_monsters1=10,deck_monsters2=15,deck_monsters3=20,
                deck_treasures1=15,deck_treasures2=20,deck_treasures3=25)


def measure(changes, seed, games):
    settings=settings_from(dict(dice_rules=1,seed=seed,**{**BASELINE,**changes}))
    routes=defaultdict(list)
    for game in range(games):
        offset=game%len(LINEUP)
        depths=LINEUP[offset:]+LINEUP[:offset]
        _,players=shared_game(settings,DEFAULT_BOARD,game,len(depths),None,depths)
        for depth,p in zip(depths,players):
            routes[depth].append(p)
    out={}
    for depth,players in sorted(routes.items()):
        scores=sorted(p['score'] for p in players)
        out[depth]=dict(players=len(players),bank=mean(scores),
                        p90=scores[int(.9*(len(scores)-1))],
                        escape=mean(p['escaped'] for p in players),
                        knocks=mean(p['knockdowns'] for p in players),
                        zero=mean(score==0 for score in scores),
                        reached=mean(max(row['zone'] for row in p['rows'])>=depth for p in players))
    return out


def misses(metrics):
    shallow,middle,deep=(metrics[i] for i in (1,2,3))
    base=max(1,shallow['bank'])
    return [
        max(0,.9-shallow['escape']), max(0,shallow['zero']-.35),
        max(0,abs(middle['bank']/base-1)-.25),
        max(0,deep['bank']/base-1.35), max(0,.75-deep['bank']/base),
        max(0,1.20-deep['p90']/max(1,shallow['p90'],middle['p90'])),
        max(0,min(shallow['zero'],.5)+.05-deep['zero']),
    ]


def run():
    trials=[]
    current={}
    for name,candidates in (
        ('hp', ({},dict(hp_min1=1,hp_max1=3),dict(hp_min3=7,hp_max3=11),
                dict(hp_min1=1,hp_max1=3,hp_min3=7,hp_max3=11))),
        ('price', ({},dict(sword_price=1,shield_price=1),dict(shield_price=1,upgrade_price=3))),
        ('treasure', ({},dict(treasure_min1=2,treasure_max1=4),dict(treasure_min1=2,treasure_max1=5),
                      dict(treasure_min1=2,treasure_max1=5,treasure_min3=2,treasure_max3=6),
                      dict(treasure_min1=2,treasure_max1=5,treasure_max2=6),
                      dict(treasure_min1=2,treasure_max1=5,treasure_min2=3,treasure_max2=6))),
    ):
        options=[]
        for changes in candidates:
            setup={**current,**changes}
            metrics=measure(setup,TRAIN_SEED,80)
            result=dict(stage=name,settings=setup,metrics=metrics,miss=sum(misses(metrics)))
            trials.append(result)
            options.append(result)
        current=min(options,key=lambda row:row['miss'])['settings']
    baseline=measure({},HOLDOUT_SEED,200)
    candidate=measure(current,HOLDOUT_SEED,200) if current else baseline
    return dict(training_seed=TRAIN_SEED,holdout_seed=HOLDOUT_SEED,trials=trials,
                baseline=baseline,candidate=candidate,settings=current,
                passes=not any(misses(candidate)))


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
