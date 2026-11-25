"""Matched five-seat baseline, adaptive routes, funnel, and buy/no-buy audit."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from math import ceil, sqrt
from pathlib import Path
from statistics import mean

from adaptive_route import adaptive_action, pick_plan
from dice_rules import mining_goal
from agent_match import AgentMatch
from engine import board_from, board_metadata, settings_from
from model import zone_at
from tune_shop import ITEMS, SEED_STRIDE, play as shop_play, summarize as shop_summary
from tune_sites import ROUTES
from tune_treasure import choose
from tune_turn_length import LINEUP, PRESET

ROLES = ('Zone 1 farm and bank', 'Zone 2', 'Zone 3')
STAGES = ('entered', 'mined', 'banked', 'surface')
LINEUPS = ('One Zone 1 farmer', 'Rotating shallow competition')


def lineup(game, rotating, seats=5):
    # In rotating games one route has a single entrant and the others two.
    if seats==5:
        depths = (1,2,3,game%3+1,(game+1)%3+1) if rotating else LINEUP
    else:
        depths = (1,2,3)+tuple((game+i)%3+1 if rotating else i%2+2
                               for i in range(seats-3))
    offset = ((game//3) if rotating else game) % seats
    anchor = (-offset)%seats
    return depths[offset:]+depths[:offset], anchor


def route_record(player, rows, depth, last_round, win):
    entry = next((row['turn'] for row in rows
                  if row['end_depth']==depth or any(zone_at(tile)==depth for tile in row.get('move_path', ()))),None)
    first_mine = next((i for i,row in enumerate(rows)
                       if row['farm_zone']==depth and row['draw_count']>0),None)
    bank = (next((row['turn'] for row in rows[first_mine+1:] if row.get('banked_now',0)>0),None)
            if first_mine is not None else None)
    mined_zones = sorted({row['farm_zone'] for row in rows if row['farm_zone'] and row['draw_count']>0})
    farm_draws = sum(row['draw_count'] for row in rows if row['action']=='Farm')
    last_deposit=max((i for i,row in enumerate(rows) if row.get('banked_now',0)>0),default=0)
    banked_zones=sorted({row['farm_zone'] for row in rows[:last_deposit]
                         if row['farm_zone'] and row['draw_count']>0})
    return dict(score=player.bank if player.escaped else 0, win=win, escaped=player.escaped,
                entered=entry, mined=rows[first_mine]['turn'] if first_mine is not None else None,
                banked=bank, surface=last_round if bank is not None and player.escaped
                and zone_at(player.position) == 0 else None,
                mined_zones=mined_zones,banked_zones=banked_zones,farm_draws=farm_draws)


def play(settings, layout, seed, game, rotating, adaptive, counts, examples, cancel,
         collect=None, assignment=None, policies=None):
    match=AgentMatch(dict(settings,seed=seed),layout)
    depths,anchor=assignment or lineup(game,rotating,len(match.players))
    goals={}
    while not match.complete:
        if cancel and cancel():
            raise InterruptedError('Study cancelled.')
        seat=match.active
        depth=depths[seat]
        actions=match.legal_actions(seat)
        selected=policies.get(depth) if policies and seat!=anchor else None
        adapting=adaptive and seat!=anchor and selected is None
        if adapting:
            plan=pick_plan(match)
            old=goals.get(seat,mining_goal(match,match.players[seat],depth) or match.board.start)
            if old!=plan.goal:
                counts[plan.reason]+=1
                if len(examples)<12:
                    examples.append(dict(seed=seed,round=match.round,seat=seat+1,
                                         position=match.players[seat].position,
                                         before=old,after=plan.goal,reason=plan.reason))
                goals[seat]=plan.goal
            action=adaptive_action(match,plan,actions)
        else:
            action=choose(match,depth,selected or ROUTES[depth-1],actions)
        match._commit(dict(actor=seat,revision=match.revision,action=action))
    winners=match.observation(0)['winners']
    result={depth: [] for depth in (1,2,3)}
    for seat,(player,depth) in enumerate(zip(match.players,depths)):
        win=1/len(winners) if seat in winners else 0
        result[depth].append(dict(seat=seat,strict=seat==anchor,
                                  **route_record(player,match.logs[seat],depth,match.round,win)))
    if collect:
        collect(match)
    return result


def interval(groups, fraction=False, signed=False):
    values=[value for group in groups for value in group]
    average=mean(values)
    games=len(groups)
    if games<2:
        return [None,None]
    margin=1.96*sqrt(games/(games-1)*sum(
        sum(value-average for value in group)**2 for group in groups))/len(values)
    if fraction and average in (0,1):
        margin=max(margin,1-.05**(1/games))
    low=average-margin
    high=average+margin
    return [low if signed else max(0,low),min(1,high) if fraction else high]


def summarize_routes(results, references=None):
    output=[]
    for depth,name in enumerate(ROLES,1):
        groups=[game[depth] for game in results]
        rows=[row for group in groups for row in group]
        scores=sorted(row['score'] for row in rows)
        wins=sum(row['win'] for row in rows)
        summary=dict(depth=depth,route=name,players=len(rows),score=mean(scores),
                     score_ci=interval([[row['score'] for row in group] for group in groups]),
                     win=wins/len(rows),
                     win_ci=interval([[row['win'] for row in group] for group in groups],fraction=True),
                     p90=scores[ceil(.9*len(scores))-1],
                     winning_score=sum(row['score']*row['win'] for row in rows)/wins if wins else None,
                     escaped=mean(row['escaped'] for row in rows))
        funnel={}
        for stage in STAGES:
            rounds=[row[stage] for row in rows if row[stage] is not None]
            funnel[stage]=dict(count=len(rounds),rate=len(rounds)/len(rows),
                               round=mean(rounds) if rounds else None)
        summary['funnel']=funnel
        if references is not None:
            deltas=[[row['score']-control['score'] for row,control in zip(group,base[depth])]
                    for group,base in zip(groups,references)]
            summary.update(delta=mean(value for group in deltas for value in group),
                           delta_ci=interval(deltas,signed=True))
        output.append(summary)
    return output


def analyze(settings, spec, board, progress=None, cancel=None):
    games=spec.get('games',60)
    if type(games) is not int or not 5<=games<=200:
        raise ValueError('Choose 5–200 games per lineup.')
    if not settings.dice_rules or settings.players!=5 or settings.turns>30:
        raise ValueError('Strategy balance uses Dice rules, five seats, and at most 30 rounds.')
    layout=board_metadata(board)['layout']
    base=asdict(settings)
    preset=dict(settings=base,board=layout)
    seeds=[(settings.seed+i*SEED_STRIDE)%(2**53) for i in range(games)]
    completed=0
    total=16*games

    def advance(phase):
        nonlocal completed
        completed+=1
        if cancel and cancel():
            raise InterruptedError('Study cancelled.')
        if progress:
            progress(dict(phase=phase,done=completed,total=total))

    comparisons=[]
    for rotating,label in enumerate(LINEUPS):
        counts=Counter()
        examples=[]
        batches=[]
        for adaptive in (False,True):
            matches=[]
            phase=('Adaptive' if adaptive else 'Fixed baseline')+' · '+label
            for game,seed in enumerate(seeds):
                matches.append(play(base,layout,seed,game,rotating,adaptive,counts,examples,cancel))
                advance(phase)
            batches.append(matches)
        fixed,adaptive=batches
        comparisons.append(dict(label=label,fixed=summarize_routes(fixed),
                                adaptive=summarize_routes(adaptive,fixed),
                                switch_reasons=dict(counts),examples=examples))

    gear=[]
    for depth,name in enumerate(ROLES,1):
        control=None
        for item in (None,*ITEMS):
            mode='opening' if item=='Boots' else 'field'
            samples=[]
            for game,seed in enumerate(seeds):
                samples.append(shop_play(preset,seed,depth,game%5,item,mode))
                advance(f'Gear audit · {name} · {item or "no purchase"}')
            if item is None:
                control=samples
            else:
                summary=shop_summary(samples,control)
                savings=mean(row['combat_damage']-actual['combat_damage']
                             for row,actual in zip(control,samples))
                gear.append(dict(route=name,item=item,control_score=mean(row['score'] for row in control),
                                 control_win=mean(row['win'] for row in control),
                                 combat_energy_saved=savings,**summary))
    return dict(games=games,seed=settings.seed,rounds=settings.turns,
                whole_moves=bool(settings.full_energy_moves),gold_shops=bool(settings.shop_gold_prices),
                settings=base,board=layout,comparisons=comparisons,gear=gear)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games',type=int,default=60)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--preset',default=str(PRESET))
    args=parser.parse_args()
    preset=json.loads(Path(args.preset).read_text())
    if args.seed is not None:
        preset['settings']['seed']=args.seed
    print(json.dumps(analyze(settings_from(preset['settings']),dict(games=args.games),
                             board_from(preset['board'])),allow_nan=False))


if __name__=='__main__':
    main()
