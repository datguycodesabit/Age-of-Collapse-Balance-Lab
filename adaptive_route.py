"""An observation-based policy that can change mining sites and depth."""
from dataclasses import dataclass
from math import ceil

from dice_rules import deck_composition, farm_open, mean_treasure, shop_price
from model import dice_move_reach, movement_cost, path_between, zone_at
from tune_treasure import END, choose


@dataclass(frozen=True)
class Plan:
    goal: tuple
    reason: str


def travel_energy(match, player, path):
    if match.settings.full_energy_moves:
        return ceil((len(path)-1)/dice_move_reach(player.equipment,match.settings))
    return sum(movement_cost(a,b,match.settings,player.equipment) for a,b in zip(path,path[1:]))


def pick_plan(match):
    player=match.players[match.active]
    settings=match.settings
    board=match.board
    position=player.position
    home=board.start
    zone=zone_at(position)
    remaining=settings.turns-match.round
    refill=settings.gain+settings.canister_gain*bool(player.items.get('Energy Canister'))
    budget=player.energy+remaining*refill
    if player.potions.get('Energy Tonic') and settings.use_potions:
        budget+=min(settings.deep_tonic_energy,settings.cap-player.energy)
    home_path=path_between(position,home,match.closed,board)
    leader=max((other.bank for i,other in enumerate(match.players) if i!=match.active and not other.killed),
               default=0)
    boss_zone=match.boss_events[-1]['active_zone'] if match.boss_events else 0
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
        if site in occupied or depth in match.closed or not match.decks[depth]:
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
        risk=counts['Monster']/50 * damage * (1 if depth==1 else depth-1)/(1+0.6*player.sword)
        spare=budget-travel-cost
        if spare<max(0.5, risk) or boss_zone and depth>=boss_zone:
            continue
        treasure=mean_treasure(settings,depth)
        gross=(counts['Treasure']*treasure+counts['Monster']*getattr(settings,f'bounty{depth}')*.65)/50
        draws=min(2 if farm else 1,len(match.decks[depth]))
        expected=gross*draws
        # Penalize travel and counterattacks. A trailing player late in the
        # match can trade efficiency for larger individual treasure cards.
        behind=max(0,leader-player.bank-player.loot)
        upside=treasure*.18 if remaining<=5 and behind>=6 else 0
        value=(expected+upside)/(cost + .27*travel + risk*(1+player.loot/12))
        if site==position and site not in player.mined_this_turn:
            value+=.12
        candidates.append((value,site))
    if not candidates:
        return Plan(home,'No reachable mine fits the return budget')
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


def adaptive_action(match, plan, actions, reference_policy):
    player=match.players[match.active]
    settings=match.settings
    board=match.board
    if player.pick_pending:
        return choose(match,zone_at(player.position),reference_policy,actions)
    if settings.turns-match.round>=5 and plan.goal!=board.start:
        priority=('Boots','Shield','Sword') if zone_at(plan.goal)>=2 else ('Shield','Sword')
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
        hit=max(0,getattr(settings,f'atk{zone_at(plan.goal)}')-player.shield*settings.shield_block_per_level)
        if player.loot==0 or player.energy>=cost+hit or {'kind':'Use','item':'Pickaxe'} in actions:
            for action in ({'kind':'Use','item':'Pickaxe'},{'kind':'Use','item':'Grenade'},{'kind':'Mine'}):
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
    return END if END in actions else actions[0]
