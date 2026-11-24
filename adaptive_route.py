"""An observation-based policy that can change mining sites and depth."""
from dataclasses import dataclass, replace
from math import ceil

from dice_rules import (boss_odds, choose_pick, combat_choice, deck_composition, farm_open,
                        mean_treasure, monster_risk, shop_price)
from model import dice_move_reach, movement_cost, neighbors, path_between, zone_at

END = {'kind': 'EndTurn'}


@dataclass(frozen=True)
class Plan:
    goal: tuple
    reason: str


def travel_energy(match, player, path):
    if match.settings.full_energy_moves:
        return ceil((len(path)-1)/dice_move_reach(player.equipment,match.settings))
    return sum(movement_cost(a,b,match.settings,player.equipment) for a,b in zip(path,path[1:]))


def pick_plan(match, returning=False):
    player=match.players[match.active]
    settings=match.settings
    board=match.board
    position=player.position
    home=board.start
    zone=zone_at(position)
    remaining=settings.turns-match.round
    refill=settings.gain+settings.canister_gain*bool(player.items.get('Energy Canister'))
    budget=player.energy+remaining*min(refill,settings.cap)
    if player.potions.get('Energy Tonic') and settings.use_potions:
        budget+=min(settings.deep_tonic_energy,settings.cap-player.energy)
    home_path=path_between(position,home,match.closed,board)
    leader=max((other.bank for i,other in enumerate(match.players) if i!=match.active and not other.killed),
               default=0)
    boss_zone=match.boss_events[-1]['active_zone'] if match.boss_events else 0
    if returning:
        return Plan(home,'Scheduled return to Surface')
    if zone and home_path:
        if budget<=travel_energy(match,player,home_path)+1:
            return Plan(home,'Return Energy is running low')
        if boss_zone and zone>=boss_zone:
            return Plan(home,'Boss threatens the current zone')
        if player.loot and remaining<=2 and player.bank+player.loot>=leader:
            return Plan(home,'Carried gold can match or beat the leader')
        if player.loot>=(7,13,19)[zone-1] and (zone==1 or remaining<=3):
            return Plan(home,'Bank a valuable haul')

    composition=deck_composition(settings)
    occupied={other.position for i,other in enumerate(match.players) if i!=match.active and not other.killed}
    candidates=[]
    for site in sorted(set(board.farms)|board.mines):
        depth=zone_at(site)
        if (depth>settings.max_zone or site in occupied or site in player.mined_this_turn
                or depth in match.closed or not match.decks[depth]):
            continue
        if (zone<2<=depth and match.round<settings.zone2_start
                or zone<3<=depth and match.round<settings.zone3_start):
            continue
        outbound=path_between(position,site,match.closed,board)
        inbound=path_between(site,home,match.closed,board)
        if not outbound or not inbound:
            continue
        travel=travel_energy(match,player,outbound)+travel_energy(match,player,inbound)
        farm=site in board.farms
        if farm and not farm_open(match,site):
            continue
        cost=settings.farm_cost if farm else settings.mine_cost
        damage=max(0,getattr(settings,f'atk{depth}')-player.shield*settings.shield_block_per_level)
        counts=composition[depth]
        draws=min(2 if farm else 1,len(match.decks[depth]))
        risk=draws*counts['Monster']/50 * damage * max(1,depth-1)/(1+0.6*player.sword)
        if settings.rolled_enemy_attacks:
            fight_energy = min(settings.cap, max(0, player.energy-travel_energy(match,player,outbound)-cost))
            knockout, lost = monster_risk(settings, depth, player, fight_energy)
            risk = draws*counts['Monster']/50 * (lost + 2*knockout)
        spare=budget-travel-cost
        if spare<max(0.5, risk) or boss_zone and depth>=boss_zone:
            continue
        treasure=mean_treasure(settings,depth)
        gross=(counts['Treasure']*treasure+counts['Monster']*getattr(settings,f'bounty{depth}')*.65)/50
        expected=gross*draws
        # Penalize travel and counterattacks. A trailing player late in the
        # match can trade efficiency for larger individual treasure cards.
        behind=max(0,leader-player.bank-player.loot)
        upside=counts['Treasure']/50*treasure*.18 if remaining<=5 and behind>=6 else 0
        value=(expected+upside)/(cost + .27*travel + risk*(1+player.loot/12))
        candidates.append((value,site))
    if not candidates:
        return Plan(home if player.loot else position,'No available mine fits the return budget')
    _,goal=max(candidates)
    if goal not in board.farms and any(tile in occupied for tile in board.farms_in(zone_at(goal))):
        reason='Farm occupied; use an open mine'
    elif 'Boots' in player.equipment and zone_at(goal)>zone:
        reason='Boots make a deeper trip affordable'
    elif remaining<=5 and leader-player.bank-player.loot>=6 and zone_at(goal)>1:
        reason='Trail the leader; seek higher-value treasure'
    else:
        reason='Better mining payoff for travel and combat cost'
    return Plan(goal,reason)


def prepare_for_boss(match, player, actions):
    s = match.settings
    if not s.boss_enabled or not s.moving_boss or 1 in match.closed or s.boss_start > s.turns:
        return None
    if match.round < s.boss_start - 2 or player.sword < 2:
        return None
    grenade = s.grenade_savings if player.grenade_armed or player.items.get('Grenade') else 0
    if player.shield < 2 and not (player.shield and grenade):
        return None
    leader = max((other.bank for other in match.players if not other.killed
                  and zone_at(other.position) == 0), default=0)
    if player.bank + s.boss_hoard < leader:
        return None
    zone = 3 - len(match.closed)
    gate = match.board.entrance(zone)
    taken = {other.position for other in match.players if other is not player and not other.killed}
    goals = [tile for tile in (gate, *neighbors(gate, match.closed, match.board))
             if zone_at(tile) == zone and tile not in taken]
    paths = [path_between(player.position, tile, match.closed, match.board) for tile in goals]
    path = min((path for path in paths if path), key=len, default=())
    if not path:
        return None
    travel = travel_energy(match, player, path)
    wait = min(2, s.turns-match.round)
    refill = s.gain + s.canister_gain*bool(player.items.get('Energy Canister'))
    projected = min(s.cap, player.energy + wait*refill - travel) - 1
    threshold = s.boss_challenge_pct / 100
    if projected <= 0 or boss_odds(s, player, projected, grenade) < threshold:
        return None
    for tonic in ({'kind':'Tonic'}, {'kind':'Use','item':'Energy Potion'}):
        if player.energy <= s.cap - 2 and tonic in actions:
            return tonic
    arm = {'kind':'Use','item':'Grenade'}
    if arm in actions:
        return arm
    if {'kind':'AttackBoss'} in actions and boss_odds(s, player, player.energy-1) >= threshold:
        return {'kind':'AttackBoss'}
    if len(path) > 1:
        moves = []
        for action in actions:
            if action['kind'] == 'Move':
                remaining = [path_between(tuple(action['destination']), goal, match.closed, match.board)
                             for goal in goals]
                distance = min((len(route) for route in remaining if route), default=len(path))
                if distance < len(path):
                    moves.append((distance, action))
        if moves:
            return min(moves, key=lambda move: move[0])[1]
    return END if wait else None


def adaptive_action(match, plan, actions):
    player=match.players[match.active]
    settings=match.settings
    board=match.board
    if player.pick_pending:
        return choose_pick(match, actions)
    if settings.rolled_enemy_attacks:
        preparation = prepare_for_boss(match, player, actions)
        if preparation:
            return preparation
    if settings.player_duels or settings.moving_boss:
        combat = combat_choice(match, actions, returning=plan.goal == board.start)
        if combat:
            return combat
    if settings.turns-match.round>=5 and plan.goal!=board.start:
        priority=('Boots','Shield','Sword') if zone_at(plan.goal)>=2 else ('Shield','Sword')
        if settings.rolled_enemy_attacks:
            zone = zone_at(plan.goal)
            current = monster_risk(settings, zone, player, 2)[0]
            def avoided_risk(item):
                upgrade = replace(player, **{item.lower(): getattr(player, item.lower())+1})
                return (current-monster_risk(settings, zone, upgrade, 2)[0])/max(1, shop_price(player,item,settings))
            weapons = tuple(item for item in ('Sword','Shield') if {'kind':'Buy','item':item} in actions)
            priority = (('Boots',) if zone>=2 else ()) + tuple(sorted(weapons, key=avoided_risk, reverse=True))
        for item in priority:
            buy={'kind':'Buy','item':item}
            if buy not in actions:
                continue
            price=shop_price(player,item,settings)
            if not settings.shop_gold_prices:
                carried=sorted(player.treasures)[:price]
                price=sum(carried)+sum(sorted(player.bank_cards)[:price-len(carried)])
            if price<=(3 if item=='Boots' else 2):
                return buy
    if player.energy<=3 and plan.goal!=player.position:
        for use in ({'kind':'Tonic'},{'kind':'Use','item':'Energy Potion'}):
            if use in actions:
                return use
    if player.position==plan.goal and plan.goal!=board.start and {'kind':'Mine'} in actions:
        cost=settings.farm_cost if plan.goal in board.farms else settings.mine_cost
        depth=zone_at(plan.goal)
        hit=max(0,getattr(settings,f'atk{depth}')-player.shield*settings.shield_block_per_level)
        safe_draw=not getattr(settings,f'deck_monsters{depth}') or player.energy>=cost+hit
        if settings.rolled_enemy_attacks:
            knockout, _ = monster_risk(settings, depth, player, player.energy-cost)
            safe_draw = knockout <= .35
        if (player.loot==0 or safe_draw or player.grenade_armed
                or {'kind':'Use','item':'Pickaxe'} in actions):
            for action in ({'kind':'Use','item':'Pickaxe'},{'kind':'Use','item':'Grenade'},
                           {'kind':'Use','item':'Shovel'},{'kind':'Mine'}):
                if action in actions:
                    return action
    if player.position!=plan.goal:
        speed={'kind':'Use','item':'Speed Potion'}
        if speed in actions:
            return speed
        current=path_between(player.position,plan.goal,match.closed,board)
        moves=[]
        for action in actions:
            if (action['kind']=='Move' or action.get('item')=='Teleport Potion'
                    and action.get('target')==match.active):
                path=path_between(tuple(action['destination']),plan.goal,match.closed,board)
                if path and (not current or len(path)<len(current)):
                    moves.append((len(path),action))
        if moves:
            return min(moves,key=lambda row:row[0])[1]
    if plan.goal != board.start:
        for use in ({'kind':'Tonic'},{'kind':'Use','item':'Energy Potion'}):
            if use in actions:
                return use
    return END if END in actions else actions[0]
