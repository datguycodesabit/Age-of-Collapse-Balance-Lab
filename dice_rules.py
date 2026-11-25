"""Dice expedition rules. Old shared-deck journals use their original resolver."""
import heapq
from functools import lru_cache
import random
from collections import deque
from dataclasses import replace

from enemy_profiles import ARCHETYPES, archetype_counts, boss_faces, fight_odds, shield_block
from model import (affordable_step, before, boss_effect, dice_move_reach, distance_home,
                   movement_cost, neighbors, path_between, record, take_potion, zone_at)
import zone_decks


DEFAULTS = {**zone_decks.DEFAULTS, 'dice_rules':1, 'gain':2, 'cap':10, 'zone2_start':1,
            'mine_cost':1, 'farm_cost':2,
            'zone3_start':1, 'atk1':1, 'atk2':2, 'atk3':3, 'bow_savings':1,
            'hp_min1':1, 'hp_max1':3, 'hp_min3':7, 'hp_max3':11,
            'deck_monsters1':10, 'deck_monsters2':13, 'deck_monsters3':17,
            'deck_treasures1':12, 'deck_treasures2':24, 'deck_treasures3':28,
            'treasure_min1':1, 'treasure_max1':4, 'treasure_min2':4, 'treasure_max2':8,
            'treasure_min3':6, 'treasure_max3':12}


def deck_composition(settings):
    composition = {}
    for zone, items in zone_decks.ITEM_CARDS.items():
        monsters = getattr(settings, f'deck_monsters{zone}')
        treasures = getattr(settings, f'deck_treasures{zone}')
        nothing = 50 - len(items) - monsters - treasures
        if min(monsters, treasures, nothing) < 0:
            raise ValueError(f'Zone {zone} Monster and Treasure counts must be nonnegative and leave room for {len(items)} Item cards.')
        composition[zone] = dict(Monster=monsters, Treasure=treasures, Nothing=nothing, Item=len(items))
    return composition


def decks(settings):
    """Shuffle once, then assign each Monster's HP and each Treasure's value."""
    piles = zone_decks.shuffled_decks(settings.seed, composition=deck_composition(settings))
    value_rng = random.Random(settings.seed + 803158657)
    value_fields = {'Monster': 'hp', 'Treasure': 'treasure'}
    valued_decks = {}
    for zone, pile in piles.items():
        valued_pile = []
        for kind, name in pile:
            field = value_fields.get(kind)
            value = None
            if field is not None:
                minimum = getattr(settings, f'{field}_min{zone}')
                maximum = getattr(settings, f'{field}_max{zone}')
                value = value_rng.randint(minimum, maximum)
            if kind == 'Monster' and settings.rolled_enemy_attacks:
                card_index = int(name.rsplit(' ', 1)[1]) - 1
                archetype = ARCHETYPES[card_index % len(ARCHETYPES)]
                value = dict(settings.monster_profiles[str(zone)][archetype], archetype=archetype)
                name = f'Z{zone} {archetype} {card_index + 1}'
            valued_pile.append((kind, name, value))
        valued_decks[zone] = valued_pile

    # All range rolls happen before overrides so profiles preserve the base RNG sequence.
    for zone_key, profile in settings.treasure_profiles.items():
        zone = int(zone_key)
        values = [int(value) for value in sorted(profile, key=int) for _ in range(profile[value])]
        random.Random(settings.seed + 18323407 * zone).shuffle(values)
        exact_values = iter(values)
        valued_decks[zone] = [
            (kind, name, next(exact_values) if kind == 'Treasure' else value)
            for kind, name, value in valued_decks[zone]
        ]
    return valued_decks


def mean_treasure(settings,zone):
    profile=settings.treasure_profiles.get(str(zone))
    if profile is not None:
        return sum(int(value)*count for value,count in profile.items())/max(1,sum(profile.values()))
    return (getattr(settings,f'treasure_min{zone}')+getattr(settings,f'treasure_max{zone}'))/2


def occupied(match, player):
    return {other.position for other in match.players if other is not player and not other.killed}


def can_stop(match,tile,taken):
    return tile==match.board.start or tile not in taken


def can_pass(match,p,destination,remaining,taken):
    """Find an unoccupied landing within the Energy left after the first step."""
    if can_stop(match,destination,taken):
        return True
    queue=[(0,destination)]
    distances={destination:0}
    while queue:
        spent,tile=heapq.heappop(queue)
        if spent>remaining:
            return False
        if can_stop(match,tile,taken):
            return True
        for other in neighbors(tile,match.closed,match.board):
            cost=spent+movement_cost(tile,other,match.settings,p.equipment)
            if cost<=remaining and cost<distances.get(other,float('inf')):
                distances[other]=cost
                heapq.heappush(queue,(cost,other))
    return False


def full_move_destinations(match, player, taken):
    """Visit tiles in increasing step count, allowing travel through other pawns."""
    if player.energy < 1:
        return []
    reach = dice_move_reach(player.equipment,match.settings)
    if player.potions.get('Haste Potion') and match.settings.use_potions:
        reach *= 2
    seen = {player.position}
    pending = deque([(player.position, 0)])
    destinations = []
    while pending:
        tile, steps = pending.popleft()
        if steps == reach:
            continue
        for other in neighbors(tile, match.closed, match.board):
            if other in seen:
                continue
            seen.add(other)
            pending.append((other, steps+1))
            if can_stop(match, other, taken):
                destinations.append(other)
    return sorted(destinations)


def landing(match,p,wanted,closed):
    taken=occupied(match,p)
    for zone in range(zone_at(wanted),-1,-1):
        if zone in closed:
            continue
        candidates=[(x,y) for y in range(10) for x in range(6)
                    if zone_at((x,y))==zone and (x,y) not in match.board.rocks
                    and can_stop(match,(x,y),taken)]
        if candidates:
            return min(candidates,key=lambda tile:(abs(tile[0]-wanted[0])+abs(tile[1]-wanted[1]),tile))
    return match.board.start


def bank(match,p):
    if p.position!=match.board.start:
        return 0
    value=p.loot
    p.bank_cards.extend(p.treasures)
    p.treasures.clear()
    p.bank+=value
    p.loot=0
    return value


def award(p,value):
    p.treasures.append(value)
    p.loot+=value


def shop_price(p,item,s):
    if item=='Boots':
        price=s.boots_price
    elif item=='Sword' and p.sword==0:
        price=s.sword_price
    elif item=='Shield' and p.shield==0:
        price=s.shield_price
    else:
        price=s.upgrade_price
    return max(0,price-int(bool(p.items.get('Coupon'))))


def shop_funds(player, settings):
    if settings.shop_gold_prices:
        return player.loot + player.bank
    return len(player.treasures) + len(player.bank_cards)


def shop_offers(match,p):
    zone=zone_at(p.position)
    levels=(('Sword',p.sword),('Shield',p.shield))
    if zone==0 and (p.position in p.board.shops or p.position==p.board.start):
        offers=[item for item,level in levels if level==0]
        if match.settings.buy_boots and 'Boots' not in p.equipment:
            offers.append('Boots')
    elif zone and (p.position in p.board.shops or
                   zone>=2 and p.position==p.board.entrance(zone)
                   and not any(zone_at(t)==zone for t in p.board.shops)):
        offers=[item for item,level in levels if 0<level<zone
                or level==0 and match.settings.field_starter_gear]
    else:
        return []
    return [item for item in offers if shop_funds(p,match.settings)>=shop_price(p,item,match.settings)]


def mining_cost(settings, site):
    return settings.farm_cost if site == 'Farm' else settings.mine_cost


def farm_open(match,tile):
    limit=match.settings.farm_shared_limit
    return not limit or match.farm_uses.get(tile,0)<limit


def mining_goal(match,player,zone):
    """Favor an available farm, defaulting to a regular mine in farm-free zones."""
    if not zone or zone in match.closed:
        return None
    farms=player.board.farms_in(zone)
    sites=farms or player.board.mines_in(zone)
    if len(sites)<=1:
        return next(iter(sites),None)
    taken=occupied(match,player)
    available=[tile for tile in sites if tile not in taken and tile not in player.mined_this_turn
               and (not farms or farm_open(match,tile))]
    return min(available or sites,
               key=lambda tile:(len(path_between(player.position,tile,match.closed,player.board)),tile))


def legal(match,actor):
    p=match.players[actor]
    zone=zone_at(p.position)
    s=match.settings
    pile=match.decks.get(zone,())
    if p.pick_pending:
        return [dict(kind='Mine',pick=i) for i in range(min(2,len(pile)))]
    taken=occupied(match,p)
    if s.full_energy_moves:
        actions=[dict(kind='Move',destination=list(tile))
                 for tile in full_move_destinations(match,p,taken)]
    else:
        actions=[]
        for tile in sorted(neighbors(p.position,match.closed,p.board)):
            step=affordable_step(p,s,tile,False)
            if step and can_pass(match,p,tile,p.energy-step[0],taken):
                actions.append(dict(kind='Move',destination=list(tile)))
    if not can_stop(match,p.position,taken):
        return actions
    if zone and p.energy > 1 and (s.player_duels or s.moving_boss):
        adjacent = neighbors(p.position, match.closed, match.board)
        if s.player_duels:
            actions.extend(dict(kind='AttackPlayer', target=seat)
                           for seat, other in enumerate(match.players)
                           if other is not p and not other.killed and not other.escaped
                           and other.energy > 0 and zone_at(other.position) == zone
                           and other.position in adjacent)
        boss = match.boss_status()
        if boss and boss['zone'] == zone and (boss['tile'] == p.position or boss['tile'] in adjacent):
            actions.append(dict(kind='AttackBoss'))
    site=zone_decks.mine_kind(p)
    if (site and pile and p.position not in p.mined_this_turn
            and (site!='Farm' or farm_open(match,p.position))):
        if p.energy>=mining_cost(s,site):
            actions.append(dict(kind='Mine'))
            if p.items.get('Pickaxe') and len(pile)>=2:
                actions.append(dict(kind='Use',item='Pickaxe'))
        if p.energy>=2 and p.items.get('Shovel'):
            actions.append(dict(kind='Use',item='Shovel'))
    if zone and p.energy>=s.mine_cost:
        x,y=p.position
        for tile in sorted(p.board.rocks):
            if abs(tile[0]-x)+abs(tile[1]-y)==1 and zone_at(tile)==zone:
                actions.append(dict(kind='Mine',destination=list(tile)))
    actions.extend(dict(kind='Buy',item=item) for item in shop_offers(match,p))
    if p.items.get('Energy Potion') and p.energy<s.cap:
        actions.append(dict(kind='Use',item='Energy Potion'))
    if p.items.get('Speed Potion') and not p.potions.get('Haste Potion') and s.use_potions:
        actions.append(dict(kind='Use',item='Speed Potion'))
    if p.items.get('Grenade') and not p.grenade_armed:
        actions.append(dict(kind='Use',item='Grenade'))
    if s.use_potions and p.potions.get('Energy Tonic') and p.energy<s.cap:
        actions.append(dict(kind='Tonic'))
    for seat,other in enumerate(match.players):
        if other.killed or zone_at(other.position)!=zone or not zone:
            continue
        if p.items.get('Thief’s Tools') and seat!=actor and other.treasures:
            actions.append(dict(kind='Use',item='Thief’s Tools',target=seat))
        if p.items.get('Teleport Potion'):
            unavailable=occupied(match,other)
            for y in range(3*zone-2,3*zone+1):
                for x in range(6):
                    tile=(x,y)
                    if tile!=other.position and tile not in p.board.rocks and tile not in unavailable:
                        actions.append(dict(kind='Use',item='Teleport Potion',target=seat,destination=[x,y]))
    return actions+[dict(kind='EndTurn')]


def move(match, p, action):
    """Pay for the move once, then process arrivals in path order."""
    destination = tuple(action['destination'])
    settings = match.settings
    start = before(p)
    if settings.full_energy_moves:
        # Skip the starting tile. Only arrivals can trigger pickups or banking.
        path = path_between(p.position, destination, match.closed, p.board)[1:]
        cost = 1
        used = ('Haste Potion',) if settings.use_potions and p.potions.get('Haste Potion') else ()
        travel = dict(move_steps=len(path), move_path=path)
    else:
        path = (destination,)
        cost, used = affordable_step(p, settings, destination, False)
        travel = {}
    if 'Boots' in p.equipment:
        p.gear_used.add('Boots')
    p.energy -= cost
    for item in used:
        take_potion(p, item)

    found_tonic = False
    cache_loot = banked = 0
    for step in path:
        p.position = step
        if step not in p.visited and zone_at(step) > 0:
            p.visited.add(step)
            if settings.deep_entry_tonic and step == p.board.entrance(3):
                found_tonic = True
                p.potions['Energy Tonic'] = p.potions.get('Energy Tonic', 0) + 1
            if step == p.board.primary_farm(3) and settings.deep_cache_loot:
                cache_loot += settings.deep_cache_loot
                award(p, settings.deep_cache_loot)
        banked += bank(match, p)

    start_distance = distance_home(start['position'], match.closed, p.board)
    end_distance = distance_home(destination, match.closed, p.board)
    action_name = 'Retreat' if end_distance < start_distance else 'Delve'
    return record(p, start, settings, action_name, match.closed, action_cost=cost,
                  loot_change=cache_loot, cache_loot=cache_loot, gate_tonic=found_tonic,
                  banked_now=banked, potions_used=list(used),
                  potions_found=['Energy Tonic'] if found_tonic else [], **travel)


def attack_bonuses(p, s):
    sword = p.sword + s.sword_damage_bonus if p.sword else 0
    bow = s.bow_savings if p.items.get('Bow') else 0
    grenade = s.grenade_savings if p.grenade_armed else 0
    return sword, bow, grenade


def fight(p, s, rng, zone, hp, *, monster_attack=None, attack_faces=None):
    """Resolve each attack and surviving monster's counterattack in order."""
    exchanges = []
    if monster_attack is None:
        monster_attack = getattr(s, f'atk{zone}')
    sword_damage, bow_damage, grenade_damage = attack_bonuses(p, s)
    block = shield_block(s, p.shield)

    while hp > 0:
        roll = rng.randint(1, 6)
        p.grenade_armed = False
        damage = roll + sword_damage + grenade_damage + bow_damage
        hp = max(0, hp - damage)

        counter_die = rng.randint(1, 6) if hp and attack_faces is not None else None
        counterattack = (attack_faces[counter_die-1] if counter_die else monster_attack) if hp else 0
        absorbed = min(block, counterattack)
        energy_hit = counterattack - absorbed
        energy_lost = min(p.energy, energy_hit)
        p.energy = max(0, p.energy - energy_hit)
        exchanges.append(dict(roll=roll, weapon=sword_damage, bow=bow_damage,
                              grenade=grenade_damage, damage=damage, hp_left=hp,
                              shield_absorbed=absorbed, hit=energy_hit, energy=p.energy))
        if attack_faces is not None:
            exchanges[-1].update(enemy_roll=counter_die, raw_attack=counterattack, energy_lost=energy_lost)
        # Mining may already have spent the last Energy. Only a hit causes defeat.
        if energy_hit and p.energy == 0:
            return exchanges, True
        grenade_damage = 0
    return exchanges, False


def knockback(match, player, zone):
    safe_zone = max(0, zone - match.settings.lose_depth)
    wanted = player.position if safe_zone == zone else match.board.exit(safe_zone)
    player.position = landing(match, player, wanted, match.closed)


def duel(match, actor, target):
    """Resolve the whole duel and give each participant their own replay row."""
    settings = match.settings
    challenger, defender = match.players[actor], match.players[target]
    starts = [before(challenger), before(defender)]
    challenger.energy -= 1
    striker, recipient = challenger, defender
    strike_seat, hit_seat = actor, target
    exchanges = []
    while recipient.energy > 0:
        roll = match.duel_rng.randint(1, 6)
        sword, bow, grenade = attack_bonuses(striker, settings)
        striker.grenade_armed = False
        strike = roll + sword + bow + grenade
        blocked = min(shield_block(settings, recipient.shield), strike - 1)
        damage = strike - blocked
        recipient.energy = max(0, recipient.energy - damage)
        exchanges.append(dict(actor=strike_seat, target=hit_seat, roll=roll, weapon=sword,
                              bow=bow, grenade=grenade, shield_absorbed=blocked,
                              damage=damage, energy=recipient.energy))
        if recipient.energy == 0:
            break
        striker, recipient = recipient, striker
        strike_seat, hit_seat = hit_seat, strike_seat

    stolen = recipient.loot
    striker.treasures.extend(recipient.treasures)
    striker.loot += stolen
    recipient.treasures.clear()
    recipient.loot = 0
    knockback(match, recipient, zone_at(recipient.position))
    rows = []
    for seat, player, start in zip((actor, target), (challenger, defender), starts):
        won = seat == strike_seat
        cost = int(seat == actor)
        rows.append(record(player, start, settings, 'Challenge' if cost else 'Defend duel', match.closed,
                           card=f'Player {strike_seat + 1} won the duel', action_cost=cost,
                           combat_cost=start['energy'] - player.energy - cost,
                           duel=dict(actor=actor, target=target, winner=strike_seat, loser=hit_seat,
                                     gold=stolen, exchanges=exchanges),
                           loot_change=stolen if won else 0, loot_penalty=0 if won else stolen,
                           knockdown='No' if won else 'Yes',
                           depth_penalty=zone_at(start['position']) - zone_at(player.position)))
    return rows


def attack_boss(match, player, rng):
    s = match.settings
    start = before(player)
    zone = zone_at(player.position)
    player.energy -= 1
    faces = boss_faces(s) if s.rolled_enemy_attacks else None
    exchanges, defeated = fight(player, s, rng, zone, s.boss_hp, monster_attack=s.boss_attack, attack_faces=faces)
    lost = hoard = 0
    if defeated:
        lost = player.loot
        player.loot = 0
        player.treasures.clear()
        knockback(match, player, zone)
    else:
        hoard = s.boss_hoard
        player.bank += hoard
        player.bank_cards.append(hoard)
    event = dict(action='Combat', target='Final boss', hp=s.boss_hp, exchanges=exchanges,
                 energy=sum(hit['hit'] for hit in exchanges), bounty=hoard, defeated=defeated)
    if faces is not None:
        event.update(attack_faces=faces, sword=player.sword, shield=player.shield,
                     grenade=bool(exchanges[0]['grenade']))
    return record(player, start, s, 'Fight boss', match.closed,
                  card='Boss defeated' if not defeated else 'Boss won and regained full health',
                  action_cost=1, combat_cost=event['energy'], combat_events=[event],
                  boss_attempt=True, boss_defeated=not defeated, boss_hoard=hoard,
                  loot_penalty=lost, knockdown='Yes' if defeated else 'No',
                  depth_penalty=zone - zone_at(player.position))


@lru_cache(maxsize=8192)
def boss_win_chance(hp, energy, bonus, grenade, counter):
    return sum(1 if hp <= roll + bonus + grenade else
               boss_win_chance(hp - roll - bonus - grenade, energy - counter, bonus, 0, counter)
               if energy > counter else 0 for roll in range(1, 7)) / 6


def boss_odds(settings, player, energy, grenade=None):
    sword, bow, armed = attack_bonuses(player, settings)
    grenade = armed if grenade is None else grenade
    block = shield_block(settings, player.shield)
    if settings.rolled_enemy_attacks:
        hits = tuple(max(0, raw-block) for raw in boss_faces(settings))
        return fight_odds(settings.boss_hp, energy, sword+bow, grenade, hits)[0]
    return boss_win_chance(settings.boss_hp, energy, sword+bow, grenade,
                           max(0, settings.boss_attack-block))


def monster_risk(settings, zone, player, energy):
    """Average fight outcomes across the configured mix, without peeking at cards."""
    sword, bow, grenade = attack_bonuses(player, settings)
    block = shield_block(settings, player.shield)
    count = getattr(settings, f'deck_monsters{zone}')
    if not count:
        return 0.0, 0.0
    knocked_down = energy_loss = 0.0
    for name, copies in zip(ARCHETYPES, archetype_counts(count)):
        if copies:
            profile = settings.monster_profiles[str(zone)][name]
            hits = tuple(max(0, raw-block) for raw in profile['faces'])
            win, lost = fight_odds(profile['hp'], energy, sword+bow, grenade, hits)
            knocked_down += copies*(1-win)
            energy_loss += copies*lost
    return knocked_down/count, energy_loss/count


@lru_cache(maxsize=8192)
def duel_win_chance(energy, other_energy, bonus, other_bonus, grenade, other_grenade):
    return sum(1 if other_energy <= damage else
               1 - duel_win_chance(other_energy - damage, energy, other_bonus, bonus, other_grenade, 0)
               for damage in (max(1, roll + bonus + grenade) for roll in range(1, 7))) / 6


def combat_choice(match, actions, returning=False):
    """Use exact dice odds from current public positions and equipment."""
    s = match.settings
    actor = match.active
    player = match.players[actor]
    if {'kind': 'AttackBoss'} in actions:
        leader = max((other.bank for other in match.players
                      if not other.killed and zone_at(other.position) == 0), default=0)
        threshold = s.boss_challenge_pct / 100 if s.rolled_enemy_attacks else .65
        if player.bank + s.boss_hoard >= leader and boss_odds(s, player, player.energy-1) >= threshold:
            return dict(kind='AttackBoss')
    return None if returning else duel_choice(match, actions, .80)


def duel_choice(match, actions, threshold):
    settings = match.settings
    player = match.players[match.active]
    sword, bow, grenade = attack_bonuses(player, settings)
    best = None
    for action in actions:
        if action['kind'] != 'AttackPlayer':
            continue
        other = match.players[action['target']]
        other_sword = other.sword + settings.sword_damage_bonus if other.sword else 0
        chance = duel_win_chance(player.energy-1, other.energy,
                                sword+bow-shield_block(settings, other.shield),
                                other_sword-shield_block(settings, player.shield),
                                grenade, 0)
        if chance >= threshold and (best is None or chance > best[0]):
            best = (chance, action)
    return best[1] if best else None


def mine(match,p,rng,action):
    """Spend Energy, resolve an ordered batch, and record the result for replay."""
    settings = match.settings
    start = before(p)
    if 'destination' in action:
        # Board layouts are immutable, so each seat needs the new layout.
        tile = tuple(action['destination'])
        p.energy -= settings.mine_cost
        match.board = replace(match.board, rocks=match.board.rocks - {tile})
        for player in match.players:
            player.board = match.board
        return record(p, start, settings, 'Mine rock', match.closed,
                      action_cost=settings.mine_cost, rock_cleared=tile)

    zone = zone_at(p.position)
    site = zone_decks.mine_kind(p)
    using_shovel = action['kind'] == 'Use'
    cost = 2 if using_shovel else mining_cost(settings, site)
    p.energy -= cost
    if site == 'Farm' and settings.farm_shared_limit:
        match.farm_uses[p.position] = match.farm_uses.get(p.position, 0) + 1

    pick = action.get('pick')
    used_items = []
    if using_shovel:
        p.items['Shovel'] -= 1
        used_items.append('Shovel')
    if p.pick_pending:
        p.pick_pending = False
        used_items.append('Pickaxe')
    # Pickaxe keeps the unchosen card in the pile, even at a two-card farm.
    draw_count = 2 if pick is None and (using_shovel or site == 'Farm') else 1
    p.farm_counts[zone] += 1
    p.mined_this_turn.add(p.position)
    pile = match.decks[zone]
    cards = []
    names = []
    found_items = []
    combat_events = []
    loot_earned = loot_lost = combat_cost = 0
    defeated = False
    for _ in range(draw_count):
        if not pile:
            break
        kind, name, value = pile.pop(pick if pick is not None else 0)
        pick = None
        cards.append(kind)
        names.append(name)
        if kind == 'Treasure':
            loot_earned += value
            award(p, value)
        elif kind == 'Item':
            p.items[name] = p.items.get(name, 0) + 1
            found_items.append(name)
        elif kind == 'Monster':
            hp, faces = (value['hp'], value['faces']) if isinstance(value, dict) else (value, None)
            exchanges, defeated = fight(p, settings, rng, zone, hp, attack_faces=faces)
            energy_hit = sum(exchange['hit'] for exchange in exchanges)
            combat_cost += energy_hit
            bounty = 0 if defeated else getattr(settings, f'bounty{zone}')
            combat_events.append(dict(action='Combat', target=name, hp=hp, exchanges=exchanges,
                                      energy=energy_hit, bounty=bounty, defeated=defeated))
            if faces is not None:
                combat_events[-1].update(archetype=value['archetype'], attack_faces=faces)
            if defeated:
                loot_lost = p.loot
                p.treasures.clear()
                p.loot = 0
                knockback(match, p, zone)
                # Leave the rest of the batch in the deck after a knockdown.
                break
            if bounty:
                loot_earned += bounty
                award(p, bounty)

    return record(p, start, settings, site, match.closed, zone=zone, farm_zone=zone,
                  action_cost=cost, cards=cards, card=' + '.join(cards), drawn=names,
                  draw_count=len(cards), items_found=found_items, items_used=used_items,
                  combat_events=combat_events, combat_cost=combat_cost, loot_change=loot_earned,
                  loot_penalty=loot_lost, empty_draws=cards.count('Nothing'),
                  knockdown='Yes' if defeated else 'No', depth_penalty=zone - zone_at(p.position))


def spend_gold(cards, price):
    paid = min(price, sum(cards))
    remaining = paid
    while remaining:
        # Prefer one card when it covers the balance. Keep any change on it.
        covering = min((value for value in cards if value >= remaining), default=None)
        value = max(cards) if covering is None else covering
        cards.remove(value)
        if value > remaining:
            cards.append(value - remaining)
        remaining -= min(value, remaining)
    return paid


def buy(match,p,item):
    start=before(p)
    price=shop_price(p,item,match.settings)
    if match.settings.shop_gold_prices:
        carried_spent=spend_gold(p.treasures,price)
        bank_spent=spend_gold(p.bank_cards,price-carried_spent)
        unit='gold'
    else:
        carried=sorted(p.treasures)[:price]
        banked=sorted(p.bank_cards)[:price-len(carried)]
        for value in carried:
            p.treasures.remove(value)
        for value in banked:
            p.bank_cards.remove(value)
        carried_spent,bank_spent=sum(carried),sum(banked)
        unit='Treasure cards'
    p.loot-=carried_spent
    p.bank-=bank_spent
    if item=='Sword':
        p.sword+=1
    elif item=='Shield':
        p.shield+=1
    else:
        p.equipment.add(item)
    return record(p,start,match.settings,'Buy '+item,match.closed,loot_spent=carried_spent,
                  bank_spent=bank_spent,card=f'{item} · {price} {unit} spent')


def resolve(match,p,rng,action):
    kind=action['kind']
    if kind=='Move':
        return move(match,p,action)
    if kind=='Mine' or kind=='Use' and action['item']=='Shovel':
        return mine(match,p,match.combat_rngs[match.active],action)
    if kind=='Buy':
        return buy(match,p,action['item'])
    return zone_decks.execute(match,p,rng,action)


def resolve_boss(match,p,event):
    carried=p.loot
    row=boss_effect(p,event,match.settings)
    if p.killed:
        p.treasures.clear()
    else:
        loss=carried-p.loot
        while loss>0 and p.treasures:
            value=min(p.treasures)
            p.treasures.remove(value)
            loss-=value
        p.loot=sum(p.treasures)
        if row['boss_ejection']:
            p.position=landing(match,p,p.position,event['closed'])
    remaining=p.loot
    banked=bank(match,p) if not p.killed else 0
    row.update(position_out=p.position,end_depth=zone_at(p.position),
               distance_home=distance_home(p.position,event['closed'],p.board),
               banked_now=banked,bank=p.bank,loot_penalty=carried-remaining,loot_out=p.loot)
    return row


def choose_pick(match, actions):
    rank = {'Treasure': 3, 'Item': 2, 'Nothing': 1, 'Monster': 0}
    pile = match.decks[zone_at(match.players[match.active].position)]
    def value(action):
        kind, _, stats = pile[action['pick']]
        if isinstance(stats, dict):
            p = match.players[match.active]
            sword, bow, grenade = attack_bonuses(p, match.settings)
            block = shield_block(match.settings, p.shield)
            hits = tuple(max(0, hit-block) for hit in stats['faces'])
            stats = fight_odds(stats['hp'], p.energy-mining_cost(match.settings, zone_decks.mine_kind(p)),
                               sword+bow, grenade, hits)[0]
        return rank[kind], stats or 0
    return max(actions, key=value)


def automated_choice(match,actions,depth,returning):
    from model import return_turns_needed

    p=match.players[match.active]
    s=match.settings
    zone=zone_at(p.position)
    end={'kind':'EndTurn'}
    if p.pick_pending:
        return choose_pick(match, actions)
    target_depth=1 if match.round<=3 else depth
    while target_depth in match.closed:
        target_depth-=1
    needed=return_turns_needed(p,s,match.closed)
    urgent=(returning or needed is None or needed+s.retreat_slack>=s.turns-match.round or
            (zone and 2 in match.closed and match.round>=s.boss_start))
    if urgent and zone==0:
        return end
    if not urgent and match.round<=s.turns-3:
        purchases=('Shield',) if depth==1 else ('Shield','Sword','Boots')
        for item in purchases:
            buy_action=dict(kind='Buy',item=item)
            if buy_action in actions:
                return buy_action
    stocking=not p.shield and shop_funds(p,s)>=shop_price(p,'Shield',s)
    safe_deposit=p.loot>=max(5,3*zone) and (zone==1 or match.round>=s.turns-4)
    home=urgent or (zone and (stocking or safe_deposit))
    goal=p.board.start if home else mining_goal(match,p,target_depth)
    if goal is None:
        for nearby in (*range(target_depth+1,depth+1),*range(target_depth-1,0,-1)):
            goal=mining_goal(match,p,nearby)
            if goal is not None:
                target_depth=nearby
                break
    if goal is None:
        home=True
        goal=p.board.start
    if s.player_duels or s.moving_boss:
        combat = combat_choice(match, actions, returning=home)
        if combat:
            return combat
    if not home and zone==target_depth and p.position==goal:
        if not match.decks[zone] and zone<depth and zone+1 not in match.closed:
            goal=mining_goal(match,p,zone+1)
            if goal is None: return end
        else:
            for item in ('Thief’s Tools','Grenade'):
                use=next((a for a in actions if a.get('item')==item),None)
                if use:
                    return use
            mine_action=dict(kind='Mine')
            pick_action=dict(kind='Use',item='Pickaxe')
            if mine_action in actions:
                attack=max(0,getattr(s,f'atk{zone}')-p.shield*s.shield_block_per_level)
                energy = p.energy-mining_cost(s,zone_decks.mine_kind(p))
                safe_draw = monster_risk(s, zone, p, energy)[0] <= .35 if s.rolled_enemy_attacks else energy >= attack
                if pick_action in actions or safe_draw or p.loot==0:
                    return pick_action if pick_action in actions else mine_action
    else:
        path=path_between(p.position,goal,match.closed,p.board)
        moves=[a for a in actions if a['kind']=='Move']
        if len(path)>1:
            if s.full_energy_moves:
                progress=[(len(route),action) for action in moves
                          for route in [path_between(tuple(action['destination']),goal,match.closed,p.board)]
                          if route and len(route)<len(path)]
                if progress:
                    return min(progress,key=lambda candidate:candidate[0])[1]
            step=dict(kind='Move',destination=list(path[1]))
            if step in moves:
                return step
            alternatives=[a for a in moves if len(path_between(tuple(a['destination']),goal,match.closed,p.board))<len(path)]
            if alternatives:
                return alternatives[0]
        if home:
            teleports=[a for a in actions if a.get('item')=='Teleport Potion' and a['target']==match.active
                       and distance_home(tuple(a['destination']),match.closed,p.board)<distance_home(p.position,match.closed,p.board)]
            if teleports:
                return min(teleports,key=lambda a:distance_home(tuple(a['destination']),match.closed,p.board))
    for action in (dict(kind='Use',item='Energy Potion'),dict(kind='Tonic'),dict(kind='Use',item='Speed Potion')):
        if action in actions:
            return action
    return end if end in actions else actions[0]
