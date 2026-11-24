"""Search treasure ranges against tuned route policies on matched seeds."""
import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from statistics import mean

from agent_match import AgentMatch
from dice_rules import choose_pick, combat_choice, farm_open, mining_goal, monster_risk
from model import dice_move_reach, path_between, zone_at


@dataclass(frozen=True)
class Policy:
    deposit: tuple
    slack: int
    gear: bool
    alternate_mines: bool
    approach: str = 'farm'


POLICIES = (
    Policy((3, 8, 12), 4, False, True),
    Policy((5, 13, 19), 3, False, True),
    Policy((7, 17, 24), 2, False, True),
    Policy((5, 14, 20), 3, True, True),
    Policy((7, 18, 24), 2, True, False),
)
CASES = (
    ((1, 4), (4, 8), (6, 12)),
    ((1, 4), (3, 7), (7, 13)),
    ((1, 4), (3, 6), (8, 14)),
    ((1, 5), (3, 7), (7, 14)),
    ((2, 4), (3, 6), (7, 12)),
    ((1, 4), (3, 7), (8, 15)),
    ((1, 3), (3, 6), (8, 15)),
    ((2, 5), (3, 6), (8, 14)),
    ((2, 5), (2, 6), (8, 14)),
    ((2, 6), (3, 6), (8, 14)),
)
FINALISTS = (
    ((2, 5), (2, 6), (8, 12)),
    ((2, 5), (2, 6), (8, 14)),
)
END = {'kind': 'EndTurn'}


def choose(match, depth, policy, actions):
    actor = match.active
    player = match.players[actor]
    settings = match.settings
    board = match.board
    position = player.position
    zone = zone_at(position)
    if player.pick_pending:
        if settings.rolled_enemy_attacks:
            return choose_pick(match, actions)
        # The pending cards are public to this seat only.
        priorities = {'Treasure': 3, 'Item': 2, 'Nothing': 1, 'Monster': 0}
        def pick_value(action):
            kind, _, value = match.decks[zone][action['pick']]
            return priorities[kind], value or 0
        return max(actions, key=pick_value)

    farm = mining_goal(match,player,depth)
    step_cost = .25 if 'Boots' in player.equipment else .5
    def travel_cost(path):
        steps=len(path)-1
        if settings.full_energy_moves:
            return ceil(steps/dice_move_reach(player.equipment,settings))
        return steps*step_cost

    round_index = match.round
    future = settings.turns - round_index
    energy_budget = player.energy + future * settings.gain
    home_path = path_between(position, board.start, match.closed, board)
    farm_path = path_between(position, farm, match.closed, board) if farm is not None else ()
    farm_home = path_between(farm, board.start, match.closed, board) if farm is not None else ()
    site_cost=settings.farm_cost if farm in board.farms else settings.mine_cost
    can_afford_excursion = (farm_path and farm_home and
                            energy_budget >= travel_cost(farm_path)+travel_cost(farm_home)
                            + site_cost + policy.slack)
    must_return = (not home_path or farm is None or depth in match.closed
                   or energy_budget <= travel_cost(home_path) + policy.slack
                   or round_index >= (settings.turns if depth == 1 else
                                      settings.boss_start + (2 if depth == 2 else 0)))
    cash_out = bool(player.loot) and (
        player.loot >= policy.deposit[depth-1] or (depth == 1 and future <= 1)
    )
    returning = must_return or cash_out or (zone == 0 and not can_afford_excursion)
    if settings.player_duels or settings.moving_boss:
        combat = combat_choice(match, actions, returning=returning)
        if combat:
            return combat
    if returning and position == board.start:
        return END
    if depth > 1 and policy.gear and round_index <= 7:
        for item in ('Boots', 'Shield', 'Sword'):
            buy = {'kind': 'Buy', 'item': item}
            if buy in actions:
                return buy

    if player.energy <= 3:
        for use in ({'kind': 'Tonic'}, {'kind': 'Use', 'item': 'Energy Potion'}):
            if use in actions:
                return use

    goal = board.start if returning else farm
    occupied = {other.position for other in match.players if other is not player and not other.killed}
    if (not returning and (policy.approach=='mine'
            or depth>1 and policy.alternate_mines
            and (farm in occupied or not farm_open(match,farm)))):
        alternatives = [tile for tile in board.mines if zone_at(tile) == depth and tile not in occupied]
        paths = [path_between(position, tile, match.closed, board) for tile in sorted(alternatives)]
        if any(paths):
            goal = min((path for path in paths if path), key=len)[-1]

    if policy.approach=='boots' and not returning and round_index<=5 and 'Boots' not in player.equipment:
        from dice_rules import shop_funds, shop_price
        if position!=board.start and shop_funds(player,settings)>=shop_price(player,'Boots',settings):
            goal=board.start
        elif zone<depth:
            goal=mining_goal(match,player,1) or goal
    if policy.approach=='late' and not returning and depth==3 and round_index<=3:
        if zone<=2:
            goal=mining_goal(match,player,2) or goal

    mine = {'kind': 'Mine'}
    if not returning and position == goal and mine in actions:
        cost = settings.farm_cost if goal in board.farms else settings.mine_cost
        hit = max(0, getattr(settings, f'atk{zone}') - player.shield*settings.shield_block_per_level)
        pick = {'kind': 'Use', 'item': 'Pickaxe'}
        if pick in actions:
            return pick
        safe_draw = player.energy >= cost + hit*(1 if depth == 1 else 2)
        if settings.rolled_enemy_attacks:
            safe_draw = monster_risk(settings, zone, player, player.energy-cost)[0] <= .35
        if not player.loot or safe_draw:
            grenade = {'kind': 'Use', 'item': 'Grenade'}
            return grenade if grenade in actions else mine

    if position != goal:
        speed = {'kind': 'Use', 'item': 'Speed Potion'}
        if speed in actions:
            return speed
        possible = []
        for action in actions:
            if action['kind'] == 'Move' or (returning and action.get('item') == 'Teleport Potion'
                                            and action.get('target') == actor):
                path = path_between(tuple(action['destination']), goal, match.closed, board)
                if path:
                    possible.append((len(path), action))
        direct = path_between(position, goal, match.closed, board)
        if possible:
            distance, move = min(possible, key=lambda pair: pair[0])
            if not direct or distance < len(direct):
                return move
    return END if END in actions else actions[0]


def measure(ranges, policies, seed, games, lone_shallow=False, board=None, cache=None):
    results = defaultdict(list)
    treasure = {f'treasure_{bound}{zone}': value
                for zone, limits in enumerate(ranges, 1)
                for bound, value in zip(('min', 'max'), limits)}
    for game in range(games):
        if lone_shallow:
            depths = [1, 2, 2, 3, 3]
            seat_offset = game % 5
        else:
            depths = [1, 2, 3, game % 3 + 1, (game+1) % 3 + 1]
            seat_offset = (game//3) % 5
        depths = depths[seat_offset:] + depths[:seat_offset]
        settings = dict(dice_rules=1, players=5, seed=seed+game*15485863, **treasure)
        if cache is not None:
            settings['deep_cache_loot'] = cache
        match = AgentMatch(settings, board)
        while not match.complete:
            actor = match.active
            depth = depths[actor]
            action = choose(match, depth, policies[depth-1], match.legal_actions(actor))
            match._commit(dict(actor=actor, revision=match.revision, action=action))
        winners = match.observation(0)['winners']
        for actor, depth in enumerate(depths):
            player = match.players[actor]
            score = player.bank if player.escaped else 0
            mined = any(row['farm_zone'] == depth for row in match.logs[actor])
            equity = 1/len(winners) if actor in winners else 0
            results[depth].append((score, player.escaped, mined, equity))
    metrics = {}
    for zone, rows in sorted(results.items()):
        scores, escapes, mining, equity = zip(*rows)
        win_score = sum(score*share for score, share in zip(scores, equity))
        scores = sorted(scores)
        metrics[zone] = dict(score=mean(scores), escape=mean(escapes), mined=mean(mining),
                             equity=mean(equity), p90=scores[int(.9*(len(scores)-1))],
                             p95=scores[int(.95*(len(scores)-1))],
                             winning_score=win_score/sum(equity) if any(equity) else None)
    return metrics


def balance_loss(metrics):
    scores = [row['score'] for row in metrics.values()]
    shares = [row['equity'] for row in metrics.values()]
    return ((max(scores)-min(scores))/max(1, mean(scores))
            + max(shares)-min(shares)
            + sum(max(0, .85-row['escape']) for row in metrics.values()))


def train(ranges, seed, games):
    profiles = [measure(ranges, (policy,)*3, seed, games) for policy in POLICIES]
    selected = [max(range(len(POLICIES)),
                    key=lambda i: (profiles[i][zone]['equity'], profiles[i][zone]['score']))
                for zone in (1, 2, 3)]
    # Check each route against the other routes' selected policies. This is
    # one best-response sweep over a finite menu.
    for zone_index in range(3):
        def evaluate(test_index):
            trial = selected.copy()
            trial[zone_index] = test_index
            row = measure(ranges, [POLICIES[i] for i in trial], seed, games)[zone_index+1]
            return row['equity'], row['score']
        selected[zone_index] = max(range(len(POLICIES)), key=evaluate)
    metrics = measure(ranges, [POLICIES[i] for i in selected], seed, games)
    return dict(ranges=ranges, policies=selected, training=metrics, loss=balance_loss(metrics))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-games', type=int, default=30)
    parser.add_argument('--holdout-games', type=int, default=150)
    parser.add_argument('--confirm', action='store_true', help='compare the two finalists in both seat mixes')
    args = parser.parse_args()
    if min(args.train_games, args.holdout_games) < 1:
        parser.error('game counts must be positive')
    if args.confirm:
        policies = [POLICIES[i] for i in (2, 2, 1)]
        for ranges in FINALISTS:
            for lone in (False, True):
                metrics = measure(ranges, policies, 9713049, args.holdout_games, lone_shallow=lone)
                print(json.dumps(dict(ranges=ranges, lone_shallow=lone, metrics=metrics,
                                      loss=balance_loss(metrics))), flush=True)
        return
    trials = []
    for ranges in CASES:
        trial = train(ranges, 8753101, args.train_games)
        trials.append(trial)
        print(json.dumps(dict(stage='training', **trial)), flush=True)
    selected = min(trials, key=lambda row: row['loss'])
    for label, trial in (('current', trials[0]), ('selected', selected)):
        metrics = measure(trial['ranges'], [POLICIES[i] for i in trial['policies']],
                          6100249, args.holdout_games)
        print(json.dumps(dict(stage='holdout', label=label, ranges=trial['ranges'],
                              policies=trial['policies'], metrics=metrics,
                              loss=balance_loss(metrics))), flush=True)


if __name__ == '__main__':
    main()
