"""Compare site layouts with the same draw seeds and with the deep cache on/off."""
import argparse
from dataclasses import replace
import json

from engine import board_metadata
from model import DEFAULT_BOARD
from tune_treasure import FINALISTS, POLICIES, measure

RANGES = FINALISTS[0]
ROUTES = (POLICIES[2], POLICIES[2], POLICIES[1])


def site_map(farm2, farm3, *, mines=None, gates=None, farm1=(0,3)):
    return replace(DEFAULT_BOARD, farms=(farm1, farm2, farm3),
                   mines=DEFAULT_BOARD.mines if mines is None else frozenset(mines),
                   gates=DEFAULT_BOARD.gates if gates is None else gates)


MAPS = {
    'original': DEFAULT_BOARD,
    'near-middle': site_map((4,4), (5,9)),
    'deep-mines-east': site_map((4,4), (5,9),
                                mines={(0,2),(3,2),(4,5),(1,5),(4,8),(5,8)}),
    'deep-mines-outer-wall': site_map((4,4), (5,9),
                                      mines={(0,2),(3,2),(4,5),(1,5),(5,7),(5,8)}),
    'middle-entry': site_map((5,4), (5,9)),
    'middle-straight': site_map((5,5), (5,9)),
    'short-bank': site_map((4,4), (5,9), farm1=(0,2),
                           mines={(0,3),(3,2),(4,5),(1,5),(1,8),(4,8)}),
    'short-bank-middle-entry': site_map((5,4), (5,9), farm1=(0,2),
                                        mines={(0,3),(3,2),(4,5),(1,5),(1,8),(4,8)}),
    'short-bank-mid-mines': site_map((5,4), (5,9), farm1=(0,2),
                                     mines={(0,3),(3,2),(4,4),(5,5),(1,8),(4,8)}),
    'mid-lane': site_map((3,5), (5,9)),
    'near-deep': site_map((5,6), (2,8)),
    'both-nearer': site_map((4,4), (2,8)),
    'deep-branch': site_map((3,5), (5,9),
                            mines={(0,2),(3,2),(4,5),(1,5),(2,7),(4,8)}),
    'shorter-gates': site_map((4,4), (5,9), gates=(0,3,1)),
    'middle-detour': site_map((2,6), (3,8)),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=80)
    parser.add_argument('--seed', type=int, default=6179023)
    parser.add_argument('--maps', choices=MAPS, nargs='+', default=list(MAPS))
    parser.add_argument('--cache', type=int, choices=(0, 6), nargs='+', default=(0, 6))
    parser.add_argument('--zone1-treasure', type=int, nargs=2, metavar=('MIN', 'MAX'),
                        default=RANGES[0])
    parser.add_argument('--both-lineups', action='store_true')
    args = parser.parse_args()
    if args.games < 1:
        parser.error('game count must be positive')
    ranges = (tuple(args.zone1_treasure), *RANGES[1:])
    for name in args.maps:
        info = board_metadata(MAPS[name])
        for cache in args.cache:
            for lone in ((True, False) if args.both_lineups else (True,)):
                metrics = measure(ranges, ROUTES, args.seed, args.games,
                                  lone_shallow=lone, board=info['layout'], cache=cache)
                print(json.dumps(dict(map=name, cache=cache, lone_shallow=lone,
                                      treasure_ranges=ranges,
                                      steps=[row['farm_to_surface'] for row in info['distances']],
                                      metrics=metrics)), flush=True)


if __name__ == '__main__':
    main()
