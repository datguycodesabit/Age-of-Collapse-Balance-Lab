"""An observation-based policy that can change mining sites and depth."""
from dataclasses import dataclass, replace
from functools import lru_cache
from math import ceil
from random import Random

from dice_rules import (boss_odds, choose_pick, combat_choice, deck_composition, duel_choice, farm_open,
                        mean_treasure, monster_risk, shop_price)
from model import dice_move_reach, movement_cost, neighbors, path_between, zone_at

END = {'kind': 'EndTurn'}


@dataclass(frozen=True)
class Personality:
    style: str
    trait: str = ''
    bank_offset: int = 0
    risk_weight: float = 1.0
    depth_bonus: float = 0.0
    middle_bonus: float = 0.0
    farm_bonus: float = 0.0
    sword_bias: float = 0.0
    duel_threshold: float = .90
    holding_value: float = .68
    patience: float = .86
    scouting_value: float = .38


STYLES = (
    Personality('Banker', bank_offset=-2, risk_weight=1.12, depth_bonus=-.20, duel_threshold=.94,
                holding_value=.48, patience=.80, scouting_value=.24),
    Personality('Delver', bank_offset=2, risk_weight=.35, depth_bonus=.65,
                holding_value=.97, patience=.99, scouting_value=.82),
    Personality('Prospector', middle_bonus=.80, farm_bonus=.16, holding_value=.74, scouting_value=.65),
    Personality('Duelist', sword_bias=.04, duel_threshold=.76),
    Personality('Boss Hunter', depth_bonus=.19, sword_bias=.08, scouting_value=.65),
)
TRAITS = ('Early banking', 'Longer trips', 'Shield first', 'Boots first')


@lru_cache(maxsize=256)
def bot_lineup(seed: int, seats: int) -> tuple[Personality, ...]:
    rng = Random(f'dice-expedition-bot:{seed}')
    lineup = []
    available = {style.style: list(TRAITS) for style in STYLES}
    while len(lineup) < seats:
        group = list(STYLES)
        rng.shuffle(group)
        for style in group[:seats-len(lineup)]:
            traits = available[style.style]
            trait = traits.pop(rng.randrange(len(traits)))
            offset = -1 if trait == 'Early banking' else 2 if trait == 'Longer trips' else 0
            lineup.append(replace(style, trait=trait, bank_offset=style.bank_offset+offset,
                                  sword_bias=style.sword_bias-.05*(trait == 'Shield first')))
    return tuple(lineup)


def close_choice(match, best, alternatives, purpose):
    if alternatives:
        rng = Random(f'dice-expedition-bot:{match.settings.seed}:{match.active}:{match.revision}:{purpose}')
        if rng.random() < .20:
            return rng.choice(alternatives)
    return best


@dataclass(frozen=True)
class Plan:
    goal: tuple
    reason: str
    wait_to_mine: bool = False


def travel_energy(match, player, path):
    if match.settings.full_energy_moves:
        return ceil((len(path)-1)/dice_move_reach(player.equipment,match.settings))
    return sum(movement_cost(a,b,match.settings,player.equipment) for a,b in zip(path,path[1:]))


def haul_value(energy, inbound, refill, turns_left, personality):
    if energy >= inbound:
        return 1.0
    if refill > 0:
        turns_home = ceil((inbound-energy)/refill)
        if turns_home <= turns_left:
            return personality.holding_value + (1-personality.holding_value)*personality.patience**turns_home
    return personality.holding_value


def mine_line(settings, player, personality, horizon, refill, outbound, inbound,
              cost, depth, draws, monster_chance, reward):
    """Search which turn to dig, branching into a clear draw, fight, or knockdown."""
    remaining = outbound
    energy = player.energy
    best = (-1.0, 0)
    hit = max(0, getattr(settings, f'atk{depth}')-player.shield*settings.shield_block_per_level)
    clear = (1-monster_chance)**draws
    route_cost = cost + .27*(outbound+inbound)
    for turn in range(horizon):
        advance = min(remaining, energy)
        remaining -= advance
        energy -= advance
        if remaining <= 0 and energy >= cost:
            after = energy-cost
            if settings.rolled_enemy_attacks:
                knocked_out, lost = monster_risk(settings, depth, player, int(after))
            else:
                knocked_out, lost = (float(hit > 0 and hit >= after), min(after, hit))
            alive = (1-monster_chance*knocked_out)**draws
            expected_loss = draws*monster_chance*lost
            fought = max(0, alive-clear)
            fight_loss = max(0, expected_loss-after*(1-alive))/fought if fought > 0 else 0
            turns_left = horizon-turn-1
            value = (clear*haul_value(after, inbound, refill, turns_left, personality)
                     + fought*haul_value(max(0, after-fight_loss), inbound, refill, turns_left, personality))
            risk = expected_loss + 2*(1-alive)
            score = (reward*max(.05, value) / (route_cost+risk*personality.risk_weight*(1+player.loot/12))
                     * personality.patience**turn)
            if score > best[0]:
                best = (score, turn)
        energy = min(settings.cap, energy+refill)
    if best[0] >= 0:
        return best
    # Value approaching a promising site beyond the horizon, with no gold banked yet.
    progress = (outbound-remaining)/(outbound+cost)
    return (reward/route_cost*personality.scouting_value*progress, horizon)


def pick_plan(match, returning=False):
    player=match.players[match.active]
    settings=match.settings
    personality = bot_lineup(settings.seed, len(match.players))[match.active]
    board=match.board
    position=player.position
    home=board.start
    zone=zone_at(position)
    remaining=settings.turns-match.round
    refill=min(settings.cap, settings.gain+settings.canister_gain*bool(player.items.get('Energy Canister')))
    budget=player.energy+remaining*refill
    horizon = min(settings.bot_lookahead, remaining + 1)
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
        if (player.loot >= (7, 13, 19)[zone-1] + personality.bank_offset
                and (zone == 1 or remaining <= 3 or personality.style == 'Banker')):
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
        outward = travel_energy(match,player,outbound)
        homeward = travel_energy(match,player,inbound)
        farm=site in board.farms
        if farm and not farm_open(match,site):
            continue
        cost=settings.farm_cost if farm else settings.mine_cost
        counts=composition[depth]
        draws=min(2 if farm else 1,len(match.decks[depth]))
        if budget < outward+homeward+cost or boss_zone and depth>=boss_zone:
            continue
        treasure=mean_treasure(settings,depth)
        gross=(counts['Treasure']*treasure+counts['Monster']*getattr(settings,f'bounty{depth}')*.65)/50
        expected=gross*draws
        # Penalize travel and counterattacks. A trailing player late in the
        # match can trade efficiency for larger individual treasure cards.
        behind=max(0,leader-player.bank-player.loot)
        upside=counts['Treasure']/50*treasure*.18 if remaining<=5 and behind>=6 else 0
        preference = (1 + personality.depth_bonus*(depth-1) + personality.middle_bonus*(depth == 2)
                      + personality.farm_bonus*farm)
        value, turn = mine_line(settings, player, personality, horizon, refill, outward, homeward,
                                cost, depth, draws, counts['Monster']/50, (expected+upside)*preference)
        candidates.append((value, site, turn))
    if not candidates:
        return Plan(home if player.loot else position,'No available mine fits the return budget')
    best, goal, turn = max(candidates)
    if zone and home_path and player.loot >= (4 if personality.style == 'Banker' else 7):
        home_cost = travel_energy(match, player, home_path)
        if home_cost <= player.energy+(horizon-1)*refill:
            bank_value = player.loot*(1-personality.holding_value)/(1+home_cost)
            if bank_value > best:
                return Plan(home, 'Bank before the next dig')
    if best > 0:
        close = [(site, ready) for value, site, ready in candidates if site != goal and value >= best*.90]
        goal, turn = close_choice(match, (goal, turn), close, 'mine')
    if goal not in board.farms and any(tile in occupied for tile in board.farms_in(zone_at(goal))):
        reason='Farm occupied; use an open mine'
    elif 'Boots' in player.equipment and zone_at(goal)>zone:
        reason='Boots make a deeper trip affordable'
    elif remaining<=5 and leader-player.bank-player.loot>=6 and zone_at(goal)>1:
        reason='Trail the leader; seek higher-value treasure'
    else:
        reason='Best mining and return line within the planning window'
    return Plan(goal, reason, position == goal and turn > 0)


def prepare_for_boss(match, player, actions):
    s = match.settings
    if not s.boss_enabled or not s.moving_boss or 1 in match.closed or s.boss_start > s.turns:
        return None
    if match.round < s.boss_start - 2:
        return None
    grenade = s.grenade_savings if player.grenade_armed or player.items.get('Grenade') else 0
    if player.sword + player.shield + bool(grenade) < 3:
        return None
    leader = max((other.bank for other in match.players if other is not player and not other.killed
                  and zone_at(other.position) == 0), default=0)
    if player.bank + s.boss_hoard < leader or player.bank + player.loot > leader:
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
    threshold = s.boss_challenge_pct / 100 if s.rolled_enemy_attacks else .65
    if projected <= 0 or boss_odds(s, player, projected, grenade) < threshold:
        return None
    for tonic in ({'kind':'Tonic'}, {'kind':'Use','item':'Energy Potion'}):
        if player.energy <= s.cap - 2 and tonic in actions:
            return tonic
    arm = {'kind':'Use','item':'Grenade'}
    if arm in actions:
        return arm
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
    personality = bot_lineup(settings.seed, len(match.players))[match.active]
    if player.pick_pending:
        return choose_pick(match, actions)
    combat = combat_choice(match, actions, returning=True)
    if combat:
        return combat
    if personality.style == 'Boss Hunter':
        preparation = prepare_for_boss(match, player, actions)
        if preparation:
            return preparation
    duel_first = False
    if (settings.player_duels and plan.goal != board.start
            and personality.style == 'Duelist' and player.loot < 8):
        home = path_between(player.position, board.start, match.closed, board)
        duel_first = bool(home) and player.energy > travel_energy(match, player, home) + 1
        if duel_first:
            duel = duel_choice(match, actions, personality.duel_threshold)
            if duel:
                return duel
    if settings.turns-match.round>=5 and plan.goal!=board.start:
        priority=('Boots','Shield','Sword') if zone_at(plan.goal)>=2 else ('Shield','Sword')
        if settings.rolled_enemy_attacks:
            zone = zone_at(plan.goal)
            current = monster_risk(settings, zone, player, 2)[0]
            def avoided_risk(item):
                upgrade = replace(player, **{item.lower(): getattr(player, item.lower())+1})
                gain = (current-monster_risk(settings, zone, upgrade, 2)[0])/max(1, shop_price(player,item,settings))
                return gain + personality.sword_bias*(item == 'Sword')
            weapons = tuple(item for item in ('Sword','Shield') if {'kind':'Buy','item':item} in actions)
            priority = (('Boots',) if zone>=2 else ()) + tuple(sorted(weapons, key=avoided_risk, reverse=True))
        elif personality.sword_bias > 0:
            priority = tuple(sorted(priority, key=lambda item: (item != 'Boots', item != 'Sword')))
        if personality.trait == 'Boots first':
            priority = ('Boots', *(item for item in priority if item != 'Boots'))
        elif personality.trait == 'Shield first' and 'Shield' in priority:
            priority = ('Shield', *(item for item in priority if item != 'Shield'))
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
    if (not plan.wait_to_mine and player.position==plan.goal
            and plan.goal!=board.start and {'kind':'Mine'} in actions):
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
    if settings.player_duels and plan.goal != board.start and not duel_first:
        duel = duel_choice(match, actions, personality.duel_threshold)
        if duel:
            return duel
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
            distance, best = min(moves,key=lambda row:row[0])
            if plan.goal == board.start:
                return best
            close = [action for steps, action in moves if steps == distance and action != best]
            return close_choice(match, best, close, 'move')
    if plan.goal != board.start:
        for use in ({'kind':'Tonic'},{'kind':'Use','item':'Energy Potion'}):
            if use in actions:
                return use
    return END if END in actions else actions[0]
