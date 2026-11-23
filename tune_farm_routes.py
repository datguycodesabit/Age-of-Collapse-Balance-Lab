"""Compare farm positions and opening Energy against a fixed shallow farmer."""
import argparse
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
from statistics import mean

from balance_study import play, summarize_routes
from engine import board_from, board_metadata, settings_from
from tune_shop import SEED_STRIDE
from tune_turn_length import PRESET

REFERENCE = {'start_energy': 2, 'farm1': (0, 2), 'farm3': (5, 9)}
VARIANTS = {
    'reference': {},
    'more-opening-energy': {'start_energy': 3},
    'large-opening-pool': {'start_energy': 4},
    'shallow-off-lane': {'farm1': (1, 2)},
    'shallow-longer': {'farm1': (1, 3)},
    'opening-energy-and-shallow-off-lane': {'start_energy': 3, 'farm1': (1, 2)},
    'deep-two-steps-closer': {'farm3': (3, 9)},
    'deep-four-steps-closer': {'farm3': (2, 8)},
    'shallow-off-lane-and-deep-closer': {'farm1': (1, 2), 'farm3': (3, 9)},
    'opening-energy-and-deep-closer': {'start_energy': 3, 'farm3': (3, 9)},
}


def trial(preset, changes, seed, games, rotating):
    variant = {**REFERENCE, **changes}
    settings = settings_from(dict(preset['settings'],start_energy=variant['start_energy']))
    board = board_from(preset['board'])
    moves={board.primary_farm(zone):variant[f'farm{zone}'] for zone in (1,2,3)
           if f'farm{zone}' in variant}
    farms = tuple(moves.get(tile,tile) for tile in board.farms)
    if any(tile in board.mines|board.shops|board.rocks for tile in farms):
        raise ValueError('An experimental farm overlaps another map site.')
    board = replace(board, farms=farms)
    layout = board_metadata(board)['layout']
    batches = []
    for adaptive in (False, True):
        counts, examples = Counter(), []
        matches = [play(asdict(settings), layout, (seed+i*SEED_STRIDE)%(2**53),
                        i, rotating, adaptive, counts, examples, None)
                   for i in range(games)]
        seats = [row for game in matches for group in game.values() for row in group]
        rates = [mean(zone in row['mined_zones'] for row in seats) for zone in (1,2,3)]
        depth_wins = [sum(row['win'] for row in seats if max(row['mined_zones'],default=0)==zone)/games
                      for zone in (1,2,3)]
        summary = summarize_routes(matches, batches[0][0] if adaptive else None)
        batches.append((matches, dict(routes=summary, mined=rates, wins_by_deepest_mine=depth_wins,
                                      deeper_share=mean(any(zone>1 for zone in row['mined_zones']) for row in seats),
                                      farm_draws=mean(row['farm_draws'] for row in seats))))
    return dict(steps=[r['farm_to_surface'] for r in board_metadata(board)['distances']],
                start_energy=settings.start_energy, fixed=batches[0][1], adaptive=batches[1][1])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games',type=int,default=50)
    parser.add_argument('--seed',type=int,default=6403279)
    parser.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS))
    parser.add_argument('--both-lineups',action='store_true')
    parser.add_argument('--preset',default=str(PRESET))
    args=parser.parse_args()
    if args.games<1:
        parser.error('game count must be positive')
    preset=json.loads(Path(args.preset).read_text())
    for name in args.variants:
        for rotating in ((False,True) if args.both_lineups else (False,)):
            result=trial(preset,VARIANTS[name],args.seed,args.games,rotating)
            print(json.dumps(dict(name=name,rotating=rotating,**result),allow_nan=False),flush=True)


if __name__=='__main__':
    main()
