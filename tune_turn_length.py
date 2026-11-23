"""Estimate tabletop turn times from complete simulated dice matches."""
import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import json
from math import ceil
from pathlib import Path
from statistics import mean

from agent_match import AgentMatch
from tune_sites import ROUTES
from tune_treasure import choose

PRESET = Path(__file__).with_name('playtests') / 'deep_upside_no_cache.json'
LINEUP = (1, 2, 2, 3, 3)


@dataclass(frozen=True)
class Timing:
    # Seconds. Replace these estimates with measured tabletop times when available.
    turn_start: float = 15
    move: float = 3
    mine: float = 5
    card: float = 5
    combat_exchange: float = 8
    bank: float = 5
    buy: float = 12
    use: float = 7
    end_turn: float = 3
    boss_roll: float = 12
    collapse: float = 15

    def action_seconds(self, action, event):
        base = {'Move': self.move, 'Mine': self.mine, 'Buy': self.buy,
                'Use': self.use, 'Tonic': self.use, 'EndTurn': self.end_turn}
        seconds = base[action['kind']] + event['draw_count'] * self.card
        if action['kind'] == 'Move':
            seconds += self.move * (event.get('move_steps',1)-1)
        seconds += self.combat_exchange * sum(
            len(combat['exchanges']) for combat in event.get('combat_events', ()))
        if event.get('banked_now', 0):
            seconds += self.bank
        return seconds


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, ceil(fraction*len(ordered))-1)]


def play(preset, seed, rounds, game, timing, routes=ROUTES):
    offset = game % len(LINEUP)
    depths = LINEUP[offset:] + LINEUP[:offset]
    match = AgentMatch(dict(preset['settings'], seed=seed, turns=rounds), preset['board'])
    turn_seconds = {}
    action_seconds = defaultdict(list)
    shared_seconds = 0
    while not match.complete:
        actor = match.active
        turn = match.round, actor
        start_boss_events = len(match.boss_events)
        action = choose(match, depths[actor], routes[depths[actor]-1], match.legal_actions(actor))
        result = match._commit(dict(actor=actor, revision=match.revision, action=action))
        seconds = timing.action_seconds(action, result['event'])
        action_seconds[result['event']['action']].append(seconds)
        turn_seconds[turn] = turn_seconds.get(turn, timing.turn_start) + seconds
        for event in match.boss_events[start_boss_events:]:
            shared_seconds += timing.boss_roll + (timing.collapse if event['collapse'] else 0)
    winners = match.observation(0)['winners']
    return dict(seed=seed, completed_round=match.round, winners=winners,
                total_seconds=sum(turn_seconds.values())+shared_seconds,
                turns=list(turn_seconds.values()), actions=action_seconds,
                seats=[dict(seat=seat, depth=depths[seat], bank=player.bank,
                            escaped=player.escaped,
                            mined=any(row['farm_zone']==depths[seat] for row in match.logs[seat]),
                            score=player.bank if player.escaped else 0,
                            win=1/len(winners) if seat in winners else 0)
                       for seat, player in enumerate(match.players)])


def summarize(matches):
    durations = [seconds for match in matches for seconds in match['turns']]
    scores = defaultdict(list)
    actions = defaultdict(list)
    for match in matches:
        for seat in match['seats']:
            scores[seat['depth']].append(seat)
        for name, seconds in match['actions'].items():
            actions[name].extend(seconds)
    return dict(
        mean_turn_seconds=mean(durations),
        p95_turn_seconds=percentile(durations,.95),
        max_turn_seconds=max(durations),
        over_60_seconds=mean(seconds>60 for seconds in durations),
        over_75_seconds=mean(seconds>75 for seconds in durations),
        mean_match_minutes=mean(match['total_seconds'] for match in matches)/60,
        p95_match_minutes=percentile([match['total_seconds'] for match in matches],.95)/60,
        action_seconds={name: dict(count=len(seconds), mean=mean(seconds))
                        for name, seconds in sorted(actions.items())},
        routes={depth: {key:mean(seat[key] for seat in seats)
                        for key in ('score','win','escaped','mined')}
                for depth, seats in sorted(scores.items())},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs=2, required=True)
    parser.add_argument('--rounds', type=int, nargs='+', default=[12, 14, 15, 16, 18])
    parser.add_argument('--games', type=int, default=100, help='games per seed block and round limit')
    parser.add_argument('--timing', type=Path, help='JSON overrides for the Timing fields, in seconds')
    parser.add_argument('--deep-slack', type=int, default=ROUTES[2].slack,
                        help="Zone 3 policy's Energy buffer for the return")
    args = parser.parse_args()
    if args.games < 1 or any(not 12 <= rounds <= 200 for rounds in args.rounds):
        parser.error('use at least one game and round limits between 12 and 200')
    if args.deep_slack < 0:
        parser.error('the Energy buffer must be nonnegative')
    timing = Timing(**json.loads(args.timing.read_text())) if args.timing else Timing()
    if any(not 0 <= seconds < float('inf') for seconds in asdict(timing).values()):
        parser.error('action timings must be finite and nonnegative')
    preset = json.loads(PRESET.read_text())
    routes = (*ROUTES[:2], replace(ROUTES[2], slack=args.deep_slack))
    print(json.dumps(dict(stage='timing', seconds=asdict(timing), deep_slack=args.deep_slack)), flush=True)
    for seed in args.seeds:
        match = play(preset, seed, 15, 0, timing, routes)
        print(json.dumps(dict(stage='exact_seed', seed=seed, rounds=match['completed_round'],
                              winners=match['winners'], seats=match['seats'],
                              minutes=match['total_seconds']/60)), flush=True)
    for rounds in args.rounds:
        for seed in args.seeds:
            matches = [play(preset, seed+game*15485863, rounds, game, timing, routes)
                       for game in range(args.games)]
            print(json.dumps(dict(stage='block', seed=seed, round_limit=rounds, games=args.games,
                                  **summarize(matches))), flush=True)


if __name__ == '__main__':
    main()
