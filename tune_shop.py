"""Measure the return on one gear purchase against matched five-seat opponents."""
import argparse
import json
from math import ceil, sqrt
from statistics import mean, stdev

from agent_match import AgentMatch
from dice_rules import mining_goal, shop_funds, shop_price
from model import path_between, zone_at
from tune_sites import ROUTES
from tune_treasure import END, choose
from tune_turn_length import LINEUP, PRESET

ITEMS = ('Shield', 'Sword', 'Boots')
STRATEGIES = ((None, 'none'),) + tuple(
    (item, mode) for mode in ('opening', 'opportunistic', 'field') for item in ITEMS
)
SEED_STRIDE = 15485863


def own_item(player, item):
    return {'Shield': player.shield > 0, 'Sword': player.sword > 0,
            'Boots': 'Boots' in player.equipment}[item]


def toward(match, player, goal, actions):
    route = path_between(player.position, goal, match.closed, match.board)
    moves = []
    for action in actions:
        if action['kind'] == 'Move':
            path = path_between(tuple(action['destination']), goal, match.closed, match.board)
            if path and (not route or len(path) < len(route)):
                moves.append((len(path), action))
    return min(moves, key=lambda pair: pair[0])[1] if moves else None


def purchase_policy(match, depth, item, mode, actions):
    player = match.players[match.active]
    board = match.board
    policy = ROUTES[depth-1]
    if item is None or own_item(player, item) or player.pick_pending:
        return choose(match, depth, policy, actions)
    buy = {'kind': 'Buy', 'item': item}
    purchase_deadline = {1: 9, 2: 8, 3: 7}[depth]
    field = mode == 'field' and item != 'Boots' and match.settings.field_starter_gear
    if field and depth > 1:
        purchase_deadline = 10
    if match.round <= purchase_deadline and buy in actions:
        return buy
    if field and match.round <= purchase_deadline:
        zone = zone_at(player.position)
        if shop_funds(player, match.settings) >= shop_price(player, item, match.settings):
            for shop in sorted(board.shops):
                if zone and zone_at(shop) == zone:
                    route = path_between(player.position, shop, match.closed, board)
                    if 1 < len(route) <= 3:
                        move = toward(match, player, shop, actions)
                        if move:
                            return move
        elif depth == 3 and player.position in board.farms_in(2) and match.round <= 5:
            mine = {'kind': 'Mine'}
            if mine in actions and player.energy >= match.settings.farm_cost + match.settings.atk2:
                return mine
            if not player.loot and END in actions:
                return END
    opening_deadline = {1: 7, 2: 5, 3: 4}[depth]
    if mode != 'opening' or match.round > opening_deadline:
        return choose(match, depth, policy, actions)

    # An opening purchase trades away early mining output and time to bank.
    if shop_funds(player, match.settings) >= shop_price(player, item, match.settings):
        goal = board.start
    else:
        goal = mining_goal(match,player,1)
        if goal is None:
            return choose(match,depth,policy,actions)
        occupied = {other.position for other in match.players if other is not player and not other.killed}
        if goal in occupied and depth > 1:
            alternatives = [tile for tile in sorted(board.mines)
                            if zone_at(tile) == 1 and tile not in occupied]
            if alternatives:
                goal = min(alternatives, key=lambda tile: len(
                    path_between(player.position, tile, match.closed, board)))
    if player.energy <= 3 and {'kind': 'Use', 'item': 'Energy Potion'} in actions:
        return {'kind': 'Use', 'item': 'Energy Potion'}
    if player.position == goal and goal != board.start and {'kind': 'Mine'} in actions:
        if {'kind': 'Use', 'item': 'Grenade'} in actions:
            return {'kind': 'Use', 'item': 'Grenade'}
        if not player.loot or player.energy >= (
                match.settings.farm_cost if goal in board.farms else match.settings.mine_cost
        ) + match.settings.atk1:
            return {'kind': 'Mine'}
    move = toward(match, player, goal, actions)
    return move or (END if END in actions else actions[0])


def play(preset, seed, depth, rotation, item, mode):
    depths = LINEUP[rotation:] + LINEUP[:rotation]
    focal = (LINEUP.index(depth) - rotation) % len(LINEUP)
    match = AgentMatch(dict(preset['settings'], seed=seed), preset['board'])
    bought_round = 0
    gold_paid = 0
    shield_saved = 0
    boots_saved = 0
    combat_damage = 0
    combat_exchanges = 0
    while not match.complete:
        actor = match.active
        actions = match.legal_actions(actor)
        if actor == focal:
            boots = 'Boots' in match.players[actor].equipment
            action = purchase_policy(match, depth, item, mode, actions)
        else:
            action = choose(match, depths[actor], ROUTES[depths[actor]-1], actions)
        event = match._commit(dict(actor=actor, revision=match.revision, action=action))['event']
        if actor != focal:
            continue
        if action['kind'] == 'Buy':
            bought_round = event['turn']
            gold_paid = event['loot_spent'] + event['bank_spent']
        if boots and action['kind'] == 'Move':
            if match.settings.full_energy_moves:
                unbooted_reach = 4 if 'Haste Potion' in event['potions_used'] else 2
                boots_saved += ceil(event['move_steps']/unbooted_reach)-1
            else:
                boots_saved += event['action_cost']
        for fight in event.get('combat_events', ()):
            combat_exchanges += len(fight['exchanges'])
            for exchange in fight['exchanges']:
                shield_saved += exchange['shield_absorbed']
                combat_damage += exchange['hit']
    player = match.players[focal]
    winners = match.observation(focal)['winners']
    return dict(score=player.bank if player.escaped else 0,
                win=1/len(winners) if focal in winners else 0,
                escaped=player.escaped,
                mined=any(row['farm_zone'] == depth for row in match.logs[focal]),
                knocked=sum(row['knockdown']=='Yes' for row in match.logs[focal]),
                bought_round=bought_round, gold_paid=gold_paid, shield_saved=shield_saved,
                boots_saved=boots_saved, combat_damage=combat_damage, combat_exchanges=combat_exchanges)


def summarize(results, control):
    bought = [row for row in results if row['bought_round']]
    differences = [row['score']-base['score'] for row,base in zip(results,control)]
    margin = 1.96*stdev(differences)/sqrt(len(differences)) if len(differences) > 1 else 0
    return dict(**{key: mean(row[key] for row in results)
                   for key in ('score','win','escaped','mined','knocked','combat_damage','combat_exchanges')},
                score_delta=mean(differences), delta_margin_95=margin,
                buy_rate=len(bought)/len(results),
                buy_round=mean(row['bought_round'] for row in bought) if bought else None,
                gold_paid=mean(row['gold_paid'] for row in bought) if bought else None,
                shield_saved=mean(row['shield_saved'] for row in bought) if bought else None,
                boots_saved=mean(row['boots_saved'] for row in bought) if bought else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', nargs='+', type=int, default=[4703017, 8319673])
    parser.add_argument('--games', type=int, default=100, help='matched games per depth, strategy and seed block')
    parser.add_argument('--starter-prices', nargs=3, type=int, metavar=('SHIELD','SWORD','BOOTS'))
    parser.add_argument('--items', nargs='+', choices=ITEMS, default=ITEMS)
    parser.add_argument('--modes', nargs='+', choices=('opening','opportunistic','field'),
                        default=('opening','opportunistic'))
    parser.add_argument('--one-mode-per-depth', action='store_true',
                        help='screen opportunistic buys in Zone 1 and opening buys in Zones 2 and 3')
    parser.add_argument('--recommended-modes', action='store_true',
                        help='screen field Sword/Shield and opening Boots on the current preset')
    args = parser.parse_args()
    if args.games < 1:
        parser.error('game count must be positive')
    preset = json.loads(PRESET.read_text())
    if args.starter_prices:
        preset['settings'].update(zip(('shield_price','sword_price','boots_price'),
                                      args.starter_prices))
    for depth in (1,2,3):
        control = None
        for item,mode in STRATEGIES:
            if item and (item not in args.items or mode not in args.modes):
                continue
            if item and args.recommended_modes and mode != ('opening' if item=='Boots' else 'field'):
                continue
            if item and args.one_mode_per_depth and mode != ('opportunistic' if depth==1 else 'opening'):
                continue
            results = [play(preset,seed+game*SEED_STRIDE,depth,game%len(LINEUP),item,mode)
                       for seed in args.seeds for game in range(args.games)]
            if control is None:
                control = results
            print(json.dumps(dict(depth=depth,item=item,mode=mode,games=len(results),
                                  **summarize(results,control))),flush=True)


if __name__ == '__main__':
    main()
