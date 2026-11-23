"""Shared cave decks and item actions for the three-action ruleset."""
import random

from model import before, neighbors, perform, record, zone_at

ITEMS = {
    'Pickaxe': 'Single use. Privately inspect the next two cards at a mine or farm and choose one.',
    'Bow': 'Permanent. Open each fight with a ranged shot that reduces its Energy cost.',
    'Speed Potion': 'Single use. Halve the cost of the next step.',
    'Energy Potion': 'Single use. Restore Energy within the cap.',
    'Energy Canister': 'Permanent. Gain extra Energy at each round refill.',
    'Grenade': 'Single use. Arm it to reduce the Energy cost of the next fight.',
    'Shovel': 'Single use. Draw up to two cards at a mine or farm for 2 Energy.',
    'Teleport Potion': 'Single use. Move an active player to an open tile in your current zone.',
    'Thief’s Tools': 'Single use. Take a random Treasure card from another active player in your zone.',
    'Coupon': 'Permanent. Pay one fewer Treasure card at a shop.',
}

COMPOSITION = {
    1: dict(Monster=10, Treasure=15, Nothing=15, Item=10),
    2: dict(Monster=15, Treasure=20, Nothing=5, Item=10),
    3: dict(Monster=20, Treasure=25, Nothing=0, Item=5),
}

ITEM_CARDS = {
    1: ('Pickaxe', 'Pickaxe', 'Bow', 'Speed Potion', 'Energy Potion', 'Energy Potion',
        'Grenade', 'Shovel', 'Shovel', 'Coupon'),
    2: ('Pickaxe', 'Bow', 'Speed Potion', 'Energy Potion', 'Energy Canister', 'Grenade',
        'Shovel', 'Teleport Potion', 'Thief’s Tools', 'Coupon'),
    3: ('Energy Potion', 'Energy Canister', 'Grenade', 'Teleport Potion', 'Thief’s Tools'),
}

# Explicit defaults for this draft ruleset. Players can tune terrain penalties back up.
DEFAULTS = {'shared_decks': 1, 'dark_cost': 1, 'rough_cost': 1, 'potion_chance': 0}


def shuffled_decks(seed, game_index=0, composition=None):
    rng = random.Random(seed + 365249069 + game_index * 15485863)
    decks = {}
    for zone, counts in (COMPOSITION if composition is None else composition).items():
        cards = [(kind, f'Z{zone} {kind} {index+1}') for kind, count in counts.items()
                 if kind != 'Item' for index in range(count)]
        cards.extend(('Item', item) for item in ITEM_CARDS[zone])
        rng.shuffle(cards)
        decks[zone] = cards
    return decks


def mine_kind(p):
    zone = zone_at(p.position)
    if zone and p.position in p.board.farms:
        return 'Farm'
    if p.position in p.board.mines:
        return 'Mine'
    return None


def price(p, item, s):
    base = s.boots_price if item == 'Boots' else s.upgrade_price
    return max(0, base - int(bool(p.items.get('Coupon'))))


def shop_offers(p, s):
    if p.position not in p.board.shops:
        return []
    offered = []
    if p.sword < 3:
        offered.append('Sword')
    if p.shield < 3:
        offered.append('Shield')
    if s.buy_boots and 'Boots' not in p.equipment:
        offered.append('Boots')
    return [item for item in offered if len(p.treasures) >= price(p,item,s)]


def legal(match, actor):
    p = match.players[actor]
    s = match.settings
    zone = zone_at(p.position)
    pile = match.decks.get(zone, ())
    if p.pick_pending:
        return [dict(kind='Mine', pick=index) for index in range(min(len(pile), 2))]
    actions = []
    for tile in sorted(neighbors(p.position, match.closed, p.board)):
        for retreat in (False, True):
            candidate = dict(kind='Move', destination=list(tile))
            if retreat:
                candidate['retreat'] = True
            if match._shared_step_allowed(p,candidate):
                actions.append(candidate)
    mine = mine_kind(p)
    can_mine = mine and p.position not in p.mined_this_turn and zone not in match.closed and pile
    if can_mine and p.energy >= (s.farm_cost if mine == 'Farm' else s.mine_cost):
        actions.append(dict(kind='Mine'))
        if len(pile) >= 2 and p.items.get('Pickaxe'):
            actions.append(dict(kind='Use',item='Pickaxe'))
    if can_mine and p.energy >= 2 and p.items.get('Shovel'):
        actions.append(dict(kind='Use',item='Shovel'))
    if p.items.get('Energy Potion') and p.energy < s.cap:
        actions.append(dict(kind='Use',item='Energy Potion'))
    if p.items.get('Speed Potion') and not p.potions.get('Haste Potion') and s.use_potions:
        actions.append(dict(kind='Use',item='Speed Potion'))
    if p.items.get('Grenade') and not p.grenade_armed:
        actions.append(dict(kind='Use',item='Grenade'))
    if p.potions.get('Energy Tonic') and p.energy < s.cap and s.use_potions:
        actions.append(dict(kind='Tonic'))
    for item in shop_offers(p,s):
        actions.append(dict(kind='Buy',item=item))
    for target, other in enumerate(match.players):
        if other.escaped or other.killed or zone_at(other.position) != zone or not zone:
            continue
        if p.items.get('Thief’s Tools') and target != actor and other.treasures:
            actions.append(dict(kind='Use',item='Thief’s Tools',target=target))
        if p.items.get('Teleport Potion'):
            for y in range(other.position[1]-(other.position[1]-1)%3, other.position[1]-(other.position[1]-1)%3+3):
                for x in range(6):
                    tile = (x,y)
                    if tile != other.position and tile not in p.board.rocks:
                        actions.append(dict(kind='Use',item='Teleport Potion',target=target,destination=list(tile)))
    if not zone and p.visited:
        actions.append(dict(kind='Extract'))
    actions.append(dict(kind='EndTurn'))
    return actions


def execute(match, p, rng, action):
    """Resolve an already validated shared-deck action."""
    kind = action['kind']
    s = match.settings
    closed = match.closed
    if kind == 'Move':
        return match._shared_move(p, rng, action, match.decks)
    if kind == 'Mine':
        mine = mine_kind(p)
        if p.pick_pending:
            p.pick_pending = False
            event = perform(p,s,rng,mine,closed=closed,deck=match.decks,pick=action['pick'])
            event['items_used'].append('Pickaxe')
            return event
        return perform(p,s,rng,mine,closed=closed,deck=match.decks)
    start = before(p)
    item = action['item']
    if kind == 'Buy':
        count = price(p,item,s)
        spent = sorted(p.treasures)[:count]
        for value in spent:
            p.treasures.remove(value)
        p.loot -= sum(spent)
        if item == 'Sword':
            p.sword += 1
        elif item == 'Shield':
            p.shield += 1
        else:
            p.equipment.add(item)
        return record(p,start,s,'Buy '+item,closed,loot_spent=sum(spent),sword=p.sword,shield=p.shield,
                      card=f'{item} · {count} Treasure cards spent')
    if item == 'Shovel':
        return perform(p,s,rng,mine_kind(p),closed=closed,deck=match.decks,shovel=True)
    p.items[item] -= 1
    bonus = 0
    details = {}
    if item == 'Pickaxe':
        p.pick_pending = True
        # The Peek command consumes the charge. Its two revealed choices are private.
        return record(p,start,s,'Use Pickaxe',closed,card='Inspect the top two cards')
    if item == 'Speed Potion':
        p.potions['Haste Potion'] = 1
    elif item == 'Energy Potion':
        bonus = min(s.cap-p.energy,s.energy_potion_gain)
        p.energy += bonus
    elif item == 'Grenade':
        p.grenade_armed = True
    elif item == 'Teleport Potion':
        target = match.players[action['target']]
        position = target.position
        target.position = tuple(action['destination'])
        details.update(target=action['target'],target_from=position,target_to=target.position)
    elif item == 'Thief’s Tools':
        target = match.players[action['target']]
        value = target.treasures.pop(rng.randrange(len(target.treasures)))
        target.loot -= value
        p.loot += value
        p.treasures.append(value)
        details.update(target=action['target'],loot_change=value)
    return record(p,start,s,'Use '+item,closed,card=item,bonus=bonus,items_used=[item],**details)


def automated_choice(match, actions, retreating):
    """Existing route preferences with a simple policy for the new inventory."""
    from model import choose_action, distance_home, path_between

    p = match.players[match.active]
    s = match.settings
    zone = zone_at(p.position)

    def offered(kind, item=None):
        return next((action for action in actions
                     if action['kind']==kind and (item is None or action.get('item')==item)), None)

    if p.pick_pending:
        priority = {'Treasure': 3, 'Item': 2, 'Nothing': 1, 'Monster': 0}
        return max(actions,key=lambda action:priority[match.decks[zone][action['pick']][0]])
    if retreating and offered('Extract'):
        return offered('Extract')
    if not retreating and match.round<=s.turns-4:
        for item in ('Boots','Sword','Shield'):
            if offered('Buy',item):
                return offered('Buy',item)
    if not retreating:
        for item in ('Thief’s Tools','Grenade'):
            if offered('Use',item):
                return offered('Use',item)
    intended,tile=choose_action(p,s,match.round,match.closed,retreating)
    if not retreating and intended in ('Mine','Farm') and offered('Mine') and offered('Use','Pickaxe'):
        return offered('Use','Pickaxe')
    if intended=='Mine' and offered('Use','Shovel'):
        return offered('Use','Shovel')
    if intended in ('Mine','Farm') and offered('Mine'):
        return offered('Mine')
    if intended=='Extract' and offered('Extract'):
        return offered('Extract')
    if not retreating and zone in match.decks and not match.decks[zone] and zone<s.max_zone:
        next_zone=zone+1
        opens=s.zone2_start if next_zone==2 else s.zone3_start
        if match.round>=opens:
            path=path_between(p.position,p.board.entrance(next_zone),match.closed,p.board)
            if len(path)>1: intended,tile='Delve',path[1]
    for action in actions:
        if (action.get('item')=='Teleport Potion' and action['target']==match.active and retreating
                and distance_home(tuple(action['destination']),match.closed,p.board)
                < distance_home(p.position,match.closed,p.board)):
            options=[option for option in actions if option.get('item')=='Teleport Potion'
                     and option['target']==match.active]
            return min(options,key=lambda option:distance_home(tuple(option['destination']),match.closed,p.board))
    if intended in ('Delve','Retreat') and tile is not None:
        if offered('Use','Speed Potion'):
            return offered('Use','Speed Potion')
        move=dict(kind='Move',destination=list(tile))
        if intended=='Retreat': move['retreat']=True
        if move in actions:
            return move
    if intended!='Rest':
        for kind,item in (('Use','Energy Potion'),('Tonic',None),('Use','Speed Potion')):
            if offered(kind,item):
                return offered(kind,item)
    return offered('EndTurn')
