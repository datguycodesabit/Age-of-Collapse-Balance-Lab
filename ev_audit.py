"""Paired counterfactuals for decisions the current simulator policy makes."""
import math
import random
import statistics
from collections import defaultdict

from model import DEFAULT_BOARD, DecisionChange, boss_timeline, run_player, validate


def options(rows):
    """Group comparable actions. Return all observed opportunities in each group."""
    groups=defaultdict(list)
    farm_count=defaultdict(int)
    for row in rows:
        turn,step=row['turn'],row['step']
        action,zone=row['action'],row['zone']
        if action in ('Farm','Mine'):
            farm_count[zone,action]+=1
            label=('First' if farm_count[zone,action]==1 else 'Repeat')+f' {action.lower()} · Zone {zone}'
            groups[label].append(DecisionChange(turn,step,'farm'))
        elif action=='Delve' and row['start_depth']<zone and row['start_depth']>0:
            groups[f'Enter Zone {zone}'].append(DecisionChange(turn,step,'gate'))
        elif action=='Delve' and zone and row['draw_count'] and not row['route_goal']:
            groups[f'Explore fresh tile · Zone {zone}'].append(DecisionChange(turn,step,'walk'))
        elif action.startswith('Buy '):
            groups[action].append(DecisionChange(turn,step,'shop',action[4:]))
        for item in row['potions_used']:
            groups[f'Use {item}'].append(DecisionChange(turn,step,'potion',item))
    return groups


ALTERNATIVES={
    'farm':'Skip the farm activation and end the turn',
    'walk':'Skip the step and end the turn',
    'gate':'Turn back toward Surface now',
    'shop':'Defer this purchase until next turn',
    'potion':'Keep the potion at this decision',
}


def paired_interval(deltas,mean):
    """Approximate interval using game clusters because boss rolls are shared."""
    by_game=defaultdict(float)
    for game,value,_ in deltas:
        by_game[game]+=value-mean
    count=len(by_game)
    if count<2:
        return None
    variance=count/(count-1)*sum(v*v for v in by_game.values())
    margin=1.96*math.sqrt(variance)/len(deltas)
    return [mean-margin,mean+margin]


def audit(s,spec,progress,cancel,board=DEFAULT_BOARD):
    validate(s)
    if s.shared_decks:
        raise ValueError('Action EV requires independent encounter rolls. Switch shared zone decks off for this audit.')
    games=spec.get('games',100)
    if type(games) is not int or not 1<=games<=500:
        raise ValueError('Choose 1–500 games for the +EV audit.')
    count=games*s.players
    if count*s.turns*(2*s.cap+2*s.farm_visits+8)>1200000:
        raise ValueError('This audit is too large. Reduce games, players, rounds or energy capacity.')
    min_ev=spec.get('minimum_ev',1)
    if type(min_ev) not in (int,float) or not math.isfinite(min_ev) or min_ev<0:
        raise ValueError('The minimum loot gain must be zero or greater.')
    groups={}
    baseline_score=0
    for game in range(games):
        schedule=boss_timeline(s,random.Random(s.seed+700000003+game*15485863))
        for player in range(s.players):
            if cancel(): raise InterruptedError('Audit cancelled.')
            index=game*s.players+player
            seed=s.seed+index*104729
            potion_seed=seed+535013
            original=run_player(s,random.Random(seed),schedule,potion_seed,board)
            baseline_score+=original['score']
            sampler=random.Random(seed+389911)
            for label,opportunities in options(original['rows']).items():
                if cancel(): raise InterruptedError('Audit cancelled.')
                # One random occurrence per category per player. Repeating one
                # action many times cannot dominate its estimate.
                change=sampler.choice(opportunities)
                alternate=run_player(s,random.Random(seed),schedule,potion_seed,board,change)
                if not alternate['change_applied']:
                    raise RuntimeError('The paired decision could not be replayed.')
                stats=groups.setdefault(label,dict(alternative=ALTERNATIVES[change.kind],
                                                   uses=0,deltas=[],original=0,alternate=0))
                stats['uses']+=len(opportunities)
                stats['original']+=original['score']
                stats['alternate']+=alternate['score']
                stats['deltas'].append((game,original['score']-alternate['score'],
                                         original['escaped']-alternate['escaped']))
        progress(dict(phase='Replaying decisions',done=game+1,total=games))
    rows=[]
    for label,stats in groups.items():
        deltas=stats['deltas']
        paired=len(deltas)
        ev=statistics.mean(value for _,value,_ in deltas)
        escape=100*statistics.mean(delta for _,_,delta in deltas)
        interval=paired_interval(deltas,ev)
        coverage=paired/count
        if paired<40 or len({game for game,_,_ in deltas})<12:
            signal='Small sample'
        elif interval[0]>0 and ev>=min_ev:
            if escape < -2:
                signal='Loot gain, lower escape'
            elif coverage>=.25:
                signal='Review for abuse'
            else:
                signal='Situational +EV'
        elif interval[1]<0:
            signal='Alternative banks more'
        else:
            signal='No clear gain'
        rows.append(dict(label=label,alternative=stats['alternative'],pairs=paired,
                         coverage=100*coverage,uses_per_player=stats['uses']/count,
                         ev=ev,interval=interval,escape_delta=escape,signal=signal,
                         action_score=stats['original']/paired,alternative_score=stats['alternate']/paired))
    rows.sort(key=lambda row:(row['signal']!='Review for abuse',-row['ev'],row['label']))
    return dict(rows=rows,games=games,players=count,seed=s.seed,baseline_score=baseline_score/count,
                minimum_ev=min_ev)
