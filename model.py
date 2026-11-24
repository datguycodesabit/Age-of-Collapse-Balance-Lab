"""Energy-driven cave rules, independent of UI and HTTP."""
import math
import random
from collections import deque
from dataclasses import dataclass, field, replace
from functools import lru_cache
from enemy_profiles import profile_defaults, validate_profiles


@dataclass
class Settings:
    turns: int = 15
    players: int = 4
    runs: int = 1000
    seed: int = 20261117
    start_energy: int = 2
    gain: int = 6
    cap: int = 10
    lose_depth: int = 1
    lose_loot: int = 2
    hp1: int = 5
    hp2: int = 8
    hp3: int = 12
    atk1: int = 2
    atk2: int = 3
    atk3: int = 3
    avg_roll: float = 4.5
    delve: int = 1
    retreat: int = 1
    retreat_start: int = 12
    adaptive_retreat: int = 0
    retreat_slack: int = 1
    zone2_start: int = 4
    zone3_start: int = 8
    loot_per_depth: int = 2
    deep_cache_loot: int = 6
    enhance: int = 2
    p_treasure: float = 25.0
    p_monster: float = 25.0
    p_enhance: float = 25.0
    dark_cost: int = 3
    rough_cost: int = 2
    boots_price: int = 3
    flashlight_price: int = 3
    climbing_price: int = 5
    buy_boots: int = 1
    buy_flashlight: int = 1
    buy_climbing: int = 1
    farm_visits: int = 3
    farm_cost: int = 2
    farm_shared_limit: int = 0
    farm_detour_limit: int = -1
    boss_enabled: int = 1
    boss_start: int = 12
    boss_threshold: int = 4
    moving_boss: int = 0
    boss_hp: int = 24
    boss_attack: int = 4
    boss_hoard: int = 35
    player_duels: int = 0
    rolled_enemy_attacks: int = 0
    boss_challenge_pct: int = 55
    monster_profiles: dict = field(default_factory=profile_defaults)
    boss_loot_loss: int = 2
    boss_energy_hit: int = 2
    pick_price: int = 5
    pack_price: int = 4
    blade_price: int = 6
    charm_price: int = 6
    battery_price: int = 8
    map_price: int = 4
    harness_price: int = 5
    buy_pick: int = 1
    buy_pack: int = 1
    buy_blade: int = 1
    buy_charm: int = 1
    buy_battery: int = 1
    buy_map: int = 1
    buy_harness: int = 1
    gear_slots: int = 3
    gear_priority: int = 0
    max_zone: int = 3
    route_policy: int = 0
    mine_cost: int = 2
    blade_savings: int = 2
    pack_protection: int = 2
    charm_bonus: int = 1
    battery_gain: int = 1
    potion_chance: float = 12.0
    use_potions: int = 1
    deep_entry_tonic: int = 1
    deep_tonic_energy: int = 3
    boots_move_range: int = 4
    shield_block_per_level: int = 1
    shared_decks: int = 0
    sword_savings: int = 2
    shield_savings: int = 1
    upgrade_price: int = 2
    bow_savings: int = 2
    grenade_savings: int = 4
    canister_gain: int = 1
    energy_potion_gain: int = 3
    dice_rules: int = 0
    hp_min1: int = 2
    hp_max1: int = 4
    hp_min2: int = 4
    hp_max2: int = 6
    hp_min3: int = 6
    hp_max3: int = 9
    treasure_min1: int = 1
    treasure_max1: int = 3
    treasure_min2: int = 2
    treasure_max2: int = 5
    treasure_min3: int = 3
    treasure_max3: int = 7
    treasure_profiles: dict = field(default_factory=dict)
    deck_monsters1: int = 10
    deck_monsters2: int = 15
    deck_monsters3: int = 20
    deck_treasures1: int = 15
    deck_treasures2: int = 20
    deck_treasures3: int = 25
    bounty1: int = 1
    bounty2: int = 2
    bounty3: int = 3
    sword_price: int = 2
    shield_price: int = 2
    field_starter_gear: int = 0
    sword_damage_bonus: int = 0
    shop_gold_prices: int = 0
    full_energy_moves: int = 0


FIELDS = [
    ('Game','turns','Turn limit'),('Game','players','Players per game'),
    ('Game','runs','Monte Carlo games'),('Game','seed','Random seed'),
    ('Strategy','retreat_start','Retreat on/after turn'),
    ('Strategy','adaptive_retreat','Energy-aware retreat (1=yes, 0=no)'),
    ('Strategy','retreat_slack','Turns of return slack'),
    ('Strategy','zone2_start','Allow Zone 2 from turn'),('Strategy','zone3_start','Allow Zone 3 from turn'),
    ('Energy','start_energy','Starting Energy (dice rules)'),
    ('Energy','gain','Energy gained per round'),('Energy','cap','Maximum energy'),
    ('Energy','delve','Base energy per outward tile'),('Energy','retreat','Base energy per retreat tile'),
    ('Equipment','dark_cost','Darkness cost multiplier'),('Equipment','rough_cost','Deep rough-ground multiplier'),
    ('Equipment','boots_price','Boots price (loot)'),('Equipment','flashlight_price','Flashlight price (loot)'),
    ('Equipment','climbing_price','Climbing Kit price (loot)'),
    ('Equipment','buy_boots','Buy Boots (1=yes, 0=no)'),
    ('Equipment','buy_flashlight','Buy Flashlight (1=yes, 0=no)'),
    ('Equipment','buy_climbing','Buy Climbing Kit (1=yes, 0=no)'),
    ('Farming','farm_visits','Paid activations before advancing'),('Farming','farm_cost','Energy per double-card activation'),
    ('Farming','mine_cost','Energy per regular mine activation'),
    ('Farming','farm_detour_limit','Maximum extra steps to visit a farm'),
    ('Boss','boss_enabled','Enable monster boss (1=yes, 0=no)'),('Boss','boss_start','Boss arrives on turn'),
    ('Boss','boss_threshold','Advance on d6 roll at least'),('Boss','boss_loot_loss','Loot lost per boss ejection'),
    ('Boss','boss_energy_hit','Energy lost per boss ejection'),
    ('Dice rules','player_duels','Enable player duels'),
    ('Dice rules','moving_boss','Enable moving, fightable boss'),
    ('Dice rules','rolled_enemy_attacks','Roll enemy attacks and use monster profiles'),
    ('Dice rules','boss_challenge_pct','Minimum bot boss win chance (%)'),
    ('Dice rules','boss_hp','Final boss HP'),('Dice rules','boss_attack','Final boss counterattack'),
    ('Dice rules','boss_hoard','Final boss hoard (gold)'),
    ('Knockdown','lose_depth','Zones pushed back'),('Knockdown','lose_loot','Loot lost'),
    ('Monsters','hp1','Zone 1 monster HP'),('Monsters','atk1','Zone 1 monster attack'),
    ('Monsters','hp2','Zone 2 monster HP'),('Monsters','atk2','Zone 2 monster attack'),
    ('Monsters','hp3','Zone 3 monster HP'),('Monsters','atk3','Zone 3 monster attack'),
    ('Monsters','avg_roll','Average player attack roll'),
    ('Rewards','loot_per_depth','Treasure reward × zone'),('Rewards','deep_cache_loot','Zone 3 cache treasure'),
    ('Rewards','enhance','Enhancement energy bonus'),
    ('Cards','p_treasure','Treasure chance (%)'),('Cards','p_monster','Monster chance (%)'),
    ('Cards','p_enhance','Enhancement chance (%)'),
    ('Strategy','max_zone','Deepest zone to attempt'),
    ('Strategy','route_policy','Route policy (0 standard, 1 mining, 2 gear, 3 deep)'),
    ('Equipment','gear_slots','Equipment slots'),
    ('Equipment','gear_priority','Shopping priority'),
    ('Potions','potion_chance','Potion find chance per encounter (%)'),
    ('Potions','use_potions','Use potions automatically'),
    ('Potions','deep_entry_tonic','Zone 3 entrance Energy Tonic (1=yes, 0=no)'),
]
FIELDS.extend(('Equipment',key,label) for key,label in (
    ('blade_savings','Cave Blade energy saved per Monster'),('pack_protection','Padded Pack loot protected'),
    ('charm_bonus','Prospector Charm extra treasure per card'),('battery_gain','Spare Battery extra Energy per turn')))
FIELDS.extend(('Zone decks',key,label) for key,label in (
    ('shared_decks','Shared 50-card zone decks (1=yes, 0=no)'),
    ('sword_savings','Sword Energy saved per upgrade'),
    ('shield_savings','Shield Energy saved per level'),
    ('upgrade_price','Sword or shield upgrade price'),
    ('bow_savings','Bow Energy saved per monster'),
    ('grenade_savings','Grenade Energy saved on next fight'),
    ('canister_gain','Energy Canister Energy per turn'),
    ('energy_potion_gain','Energy Potion Energy restored')))
FIELDS.extend(('Dice rules',key,label) for key,label in (
    ('dice_rules','Dice combat and repeat banking (1=yes, 0=no)'),
    ('sword_price','Level 1 Sword price'),
    ('shield_price','Level 1 Shield price'),
    ('shop_gold_prices','Dice shop prices in gold (1=yes, 0=cards)'),
    ('full_energy_moves','Move up to two squares for 1 Energy (1=yes, 0=no)'),
    ('field_starter_gear','Sell starter Sword and Shield underground (1=yes, 0=no)'),
    ('sword_damage_bonus','Extra damage with an equipped Sword')))
FIELDS.extend(('Dice rules',key,label) for key,label in (
    ('farm_shared_limit','Farm uses per site per round (0 = unlimited)'),
    ('deep_tonic_energy','Entrance Tonic Energy'),
    ('boots_move_range','Maximum squares per Move with Boots'),
    ('shield_block_per_level','Energy blocked per Shield level')))
for zone_number in (1,2,3):
    for prefix,label in (('hp_min','minimum monster HP'),('hp_max','maximum monster HP'),
                         ('treasure_min','minimum treasure'),('treasure_max','maximum treasure'),
                         ('bounty','monster bounty'),('deck_monsters','Monster cards'),
                         ('deck_treasures','Treasure cards')):
        FIELDS.append(('Dice rules',f'{prefix}{zone_number}',f'Zone {zone_number} {label}'))
BOARD_WIDTH, BOARD_HEIGHT = 6, 10
FARMS = {1:(0,3), 2:(5,6), 3:(5,9)}
EXITS = {0:(0,0), 1:(5,3), 2:(0,6)}
SHOPS = {(0,0), (5,3), (0,6), (0,7)}
GATES = {1:0, 4:5, 7:0}
GEAR = {'Boots':('boots_price','buy_boots'), 'Flashlight':('flashlight_price','buy_flashlight'),
        'Climbing Kit':('climbing_price','buy_climbing'),
        'Mining Pick':('pick_price','buy_pick'), 'Padded Pack':('pack_price','buy_pack'),
        'Cave Blade':('blade_price','buy_blade'), 'Prospector Charm':('charm_price','buy_charm'),
        'Spare Battery':('battery_price','buy_battery'), 'Trail Map':('map_price','buy_map'),
        'Safety Harness':('harness_price','buy_harness')}
GEAR_EFFECTS = {
    'Boots':'Halve tile movement costs.',
    'Flashlight':'Remove the darkness surcharge in Zones 2 and 3.',
    'Climbing Kit':'Remove the rough-ground surcharge in Zone 3.',
    'Mining Pick':'Spend 1 less energy per farm activation (minimum 1).',
    'Padded Pack':'Protect carried loot on a monster knockdown.',
    'Cave Blade':'Reduce combat energy cost per Monster card.',
    'Prospector Charm':'Earn extra loot per Treasure card.',
    'Spare Battery':'Regenerate extra energy per turn, within the cap.',
    'Trail Map':'Reduce retreat movement cost by 0.5 energy (minimum 0.25).',
    'Safety Harness':'Prevent one zone of monster pushback and reduce boss ejection losses.',
}
POTIONS = {
    'Energy Tonic':'Restore up to 3 energy when you cannot afford the next action.',
    'Haste Potion':'Halve the cost of one affordable step when it saves energy.',
    'Glow Potion':'Remove darkness from one affordable dark step without a Flashlight.',
    'Ward Potion':'Reduce one unaffordable combat batch by up to 4 energy.',
    'Fortune Potion':'Earn 3 extra loot on the next Treasure batch.',
}
PRIORITIES = (
    ('Flashlight','Boots','Climbing Kit','Cave Blade','Mining Pick','Spare Battery','Prospector Charm','Trail Map','Padded Pack','Safety Harness'),
    ('Mining Pick','Prospector Charm','Cave Blade','Padded Pack','Spare Battery','Boots','Flashlight','Climbing Kit','Trail Map','Safety Harness'),
    ('Flashlight','Climbing Kit','Boots','Spare Battery','Cave Blade','Trail Map','Safety Harness','Mining Pick','Padded Pack','Prospector Charm'),
    ('Boots','Trail Map','Safety Harness','Padded Pack','Spare Battery','Flashlight','Cave Blade','Climbing Kit','Mining Pick','Prospector Charm'),
)
for item, (price, enabled) in list(GEAR.items())[3:]:
    FIELDS.extend((('Equipment',price,item+' price (loot)'),('Equipment',enabled,'Buy '+item)))


def zone_at(position):
    return 0 if position[1] == 0 else (position[1]-1)//3+1


@dataclass(frozen=True)
class Board:
    gates: tuple = (0,5,0)
    farms: tuple = ((0,3),(5,6),(5,9))
    shops: frozenset = frozenset(SHOPS)
    rocks: frozenset = frozenset()
    shop_detours: bool = False
    mines: frozenset = frozenset()

    @property
    def start(self):
        return self.gates[0],0

    def entrance(self,zone):
        return self.gates[zone-1],3*zone-2

    def exit(self,zone):
        x,y=self.entrance(zone+1)
        return x,y-1

    def farms_in(self,zone):
        return tuple(tile for tile in self.farms if zone_at(tile)==zone)

    def primary_farm(self,zone):
        return next(iter(self.farms_in(zone)),None)

    def mines_in(self,zone):
        return tuple(sorted(tile for tile in self.mines if zone_at(tile)==zone))

    def move_farm(self,old,new):
        farms=tuple(sorted((tile if tile!=old else new for tile in self.farms),
                           key=lambda tile:(tile[1],tile[0])))
        mines=(self.mines-{new})|{old} if new in self.mines else self.mines
        return replace(self,farms=farms,mines=mines)


DEFAULT_BOARD = Board(mines=frozenset({(0,2),(3,2),(4,5),(1,5),(1,8),(4,8)}))


def neighbors(position, closed=(), board=DEFAULT_BOARD):
    x,y=position
    if zone_at(position) in closed or position in board.rocks: return ()
    result=[]
    for nx,ny in ((x,y-1),(x-1,y),(x+1,y),(x,y+1)):
        if not (0<=nx<6 and 0<=ny<10) or zone_at((nx,ny)) in closed or (nx,ny) in board.rocks: continue
        boundary=max(y,ny)
        if ny!=y and boundary in GATES and x!=board.gates[(boundary-1)//3]: continue
        result.append((nx,ny))
    return tuple(result)


@lru_cache(maxsize=16000)
def path_between(start,goal,closed=(),board=DEFAULT_BOARD):
    if (zone_at(start) in closed or zone_at(goal) in closed
            or start in board.rocks or goal in board.rocks): return ()
    queue=deque([start]);parents={start:None}
    while queue:
        current=queue.popleft()
        if current==goal:
            path=[]
            while current is not None: path.append(current);current=parents[current]
            return tuple(reversed(path))
        for destination in neighbors(current,closed,board):
            if destination not in parents: parents[destination]=current;queue.append(destination)
    return ()


def distance_home(position,closed=(),board=DEFAULT_BOARD):
    if zone_at(position)==0: return 0
    path=path_between(position,board.start,tuple(closed),board)
    return len(path)-1 if path else None


def detour_steps(board,zone,farm=None):
    entry,exit_tile=board.entrance(zone),board.exit(zone)
    farm=board.primary_farm(zone) if farm is None else farm
    if farm is None:
        return 0
    return (len(path_between(entry,farm,(),board))
            +len(path_between(farm,exit_tile,(),board))
            -len(path_between(entry,exit_tile,(),board))-1)


def skips_farm(p,s,zone,closed):
    return (s.farm_detour_limit>=0 and zone<s.max_zone and zone+1 not in closed
            and detour_steps(p.board,zone)>s.farm_detour_limit)


def combat(zone,s):
    hp=(s.hp1,s.hp2,s.hp3)[zone-1];attack=(s.atk1,s.atk2,s.atk3)[zone-1]
    rounds=math.ceil(hp/s.avg_roll)
    return hp,attack,rounds,rounds*s.delve+max(0,rounds-1)*attack


def movement_cost(start,destination,s,equipment,retreating=False,glow=False):
    zone=max(zone_at(start),zone_at(destination))
    cost=s.retreat if retreating else s.delve
    if s.dice_rules: cost/=2
    if zone>=2 and 'Flashlight' not in equipment and not glow: cost*=s.dark_cost
    if zone==3 and 'Climbing Kit' not in equipment: cost*=s.rough_cost
    if 'Boots' in equipment: cost/=2
    if retreating and 'Trail Map' in equipment: cost=max(.25,cost-.5)
    return cost


def dice_move_reach(equipment,s):
    return s.boots_move_range if 'Boots' in equipment else 2


def boss_timeline(s,rng):
    active=3;closed=[];events=[]
    for turn in range(1,s.turns+1):
        die=collapse=0
        threatened=active if s.boss_enabled and turn>=s.boss_start else 0
        if threatened:
            die=rng.randint(1,6)
            if die>=s.boss_threshold: collapse=active;closed.append(active);active-=1
        events.append(dict(turn=turn,die=die,threatened=threatened,collapse=collapse,entrance_sealed=active==0,
                           active_zone=active if threatened else 0,closed=sorted(closed)))
    return events


def boss_advance_threshold(s, turn):
    return max(2, 5 - (turn - s.boss_start))


def moving_boss_round(s, rng, turn, closed):
    zone = 3 - len(closed)
    threatened = zone if s.boss_enabled and turn >= s.boss_start else 0
    threshold = boss_advance_threshold(s, turn) if threatened else None
    die = rng.randint(1, 6) if threatened else 0
    collapse = zone if threatened and die >= threshold else 0
    if collapse:
        closed = tuple(sorted((*closed, collapse)))
    return dict(turn=turn, die=die, threatened=threatened, collapse=collapse,
                entrance_sealed=1 in closed, active_zone=3-len(closed) if threatened else 0,
                closed=list(closed), threshold=threshold)


@dataclass
class Player:
    board: Board = DEFAULT_BOARD
    position: tuple = (0,0)
    energy: float = 0
    loot: int = 0
    bank: int = 0
    visited: set = field(default_factory=set)
    equipment: set = field(default_factory=set)
    gear_used: set = field(default_factory=set)
    potions: dict = field(default_factory=dict)
    potion_rng: object = None
    farm_counts: dict = field(default_factory=lambda:{1:0,2:0,3:0})
    mined_this_turn: set = field(default_factory=set)
    escaped: bool = False
    killed: bool = False
    items: dict = field(default_factory=dict)
    treasures: list = field(default_factory=list)
    bank_cards: list = field(default_factory=list)
    sword: int = 1
    shield: int = 0
    grenade_armed: bool = False
    pick_pending: bool = False


def before(p):
    return dict(position=p.position,energy=p.energy,loot=p.loot)


def record(p,start,s,action,closed=(),**extra):
    row=dict(action=action,position_in=start['position'],position_out=p.position,
             zone=zone_at(p.position),start_depth=zone_at(start['position']),end_depth=zone_at(p.position),
             distance_home=distance_home(p.position,tuple(closed),p.board),visited=len(p.visited),
             start_energy=start['energy'],gain=0,available=start['energy'],
             card='—',cards=[],draw_count=0,roll='',monster_hp=0,monster_attack=0,rounds=0,
             combat_cost=0,action_cost=0,bonus=0,raw_energy=p.energy,end_energy=p.energy,
             loot_in=start['loot'],loot_change=0,cache_loot=0,loot_penalty=0,loot_spent=0,loot_out=p.loot,
             depth_penalty=0,knockdown='No',escaped='Yes' if p.escaped else 'No',bank=p.bank,
             equipment=sorted(p.equipment),collapsed=list(closed),boss_roll=0,boss_zone=0,
             boss_ejection=False,farm_zone=0,empty_draws=0,potions=dict(p.potions),potions_found=[],potions_used=[],
             gate_tonic=False,
             walking_savings={},route_goal='',wait_for='',killed=p.killed)
    row.update(extra);return row


def buy(p,name,s,closed=()):
    if name not in GEAR or p.position not in p.board.shops or zone_at(p.position) in closed: return None
    price_key,flag=GEAR[name];price=getattr(s,price_key)
    if not getattr(s,flag) or name in p.equipment or p.loot<price or len(p.equipment)>=s.gear_slots: return None
    start=before(p);p.loot-=price;p.equipment.add(name)
    return record(p,start,s,'Buy '+name,closed,loot_spent=price,card='Purchased '+name)


def affordable_step(p,s,destination,retreating,held_potion=None):
    normal=movement_cost(p.position,destination,s,p.equipment,retreating)
    options=[(normal,())]
    if s.use_potions and held_potion!='Glow Potion' and p.potions.get('Glow Potion'):
        lit=movement_cost(p.position,destination,s,p.equipment,retreating,glow=True)
        if lit<normal: options.append((lit,('Glow Potion',)))
    if s.use_potions and held_potion!='Haste Potion' and p.potions.get('Haste Potion'):
        options.extend((price/2,names+('Haste Potion',)) for price,names in tuple(options))
    affordable=[option for option in options if option[0]<=p.energy]
    if not affordable: return None
    if normal<=p.energy:
        return min((o for o in affordable if len(o[1])<=1),key=lambda o:o[0])
    return min(affordable,key=lambda o:(len(o[1]),o[0]))


def perform(p,s,rng,action,destination=None,closed=(),held_potion=None,deck=None,pick=None,shovel=False):
    """Reject invalid/unaffordable actions before state or RNG mutation."""
    used=[]
    walking_savings={}
    mining=action in ('Farm','Mine')
    if mining:
        zone=zone_at(p.position)
        if not zone or zone in closed or p.position in p.mined_this_turn: return None
        if action=='Farm' and p.position not in p.board.farms: return None
        if action=='Mine' and p.position not in p.board.mines: return None
        base_cost=2 if shovel else s.farm_cost if action=='Farm' else s.mine_cost
        cost=max(1,base_cost-int('Mining Pick' in p.equipment))
    elif action in ('Delve','Retreat'):
        if destination not in neighbors(p.position,closed,p.board): return None
        zone=zone_at(destination)
        step=affordable_step(p,s,destination,action=='Retreat',held_potion)
        if step is None: return None
        cost,names=step
        used.extend(names)
    else: return None
    if p.energy<cost: return None
    if mining and cost<base_cost:
        p.gear_used.add('Mining Pick')
    if not mining:
        glow='Glow Potion' in used
        base=movement_cost(p.position,destination,s,p.equipment,action=='Retreat',glow)
        for item in ('Boots','Flashlight','Climbing Kit','Trail Map'):
            if item not in p.equipment: continue
            difference=movement_cost(p.position,destination,s,p.equipment-{item},
                                     action=='Retreat',glow)-base
            if difference>0:
                p.gear_used.add(item)
                walking_savings[item]=difference/(2 if 'Haste Potion' in used else 1)
    start=before(p);p.energy-=cost
    for name in used: take_potion(p,name)
    if not mining: p.position=destination
    discoveries=action=='Delve' and zone>0 and p.position not in p.visited
    if mining:
        p.farm_counts[zone]+=1
        p.mined_this_turn.add(p.position)
    if discoveries: p.visited.add(p.position)
    draws=1 if pick is not None else 2 if action=='Farm' or shovel else int(action=='Mine' or discoveries)
    cache_loot=s.deep_cache_loot if discoveries and p.position==p.board.primary_farm(3) else 0
    gate_tonic=bool(s.deep_entry_tonic and discoveries and p.position==p.board.entrance(3))
    cards=[];rolls=[];earned=cache_loot;bonus=combat_cost=rounds=0
    drawn=[];items_found=[];items_used=[]
    combat_events=[]
    if deck is not None and cache_loot:
        p.treasures.append(cache_loot)
    for _ in range(draws):
        if deck is not None:
            pile=deck[zone]
            if not pile: break
            card,identity=pile.pop(pick if pick is not None else 0)
            drawn.append(identity)
            pick=None
        else:
            roll=rng.random();rolls.append(round(roll,5))
            if roll<s.p_treasure/100: card='Treasure'
            elif roll<(s.p_treasure+s.p_monster)/100: card='Monster'
            elif roll<(s.p_treasure+s.p_monster+s.p_enhance)/100: card='Enhancement'
            else: card='Nothing'
        if card=='Treasure':
            value=zone*s.loot_per_depth+s.charm_bonus*int('Prospector Charm' in p.equipment)
            earned+=value
            if deck is not None: p.treasures.append(value)
            if s.charm_bonus and 'Prospector Charm' in p.equipment: p.gear_used.add('Prospector Charm')
        elif card=='Monster':
            card='Monster';_,_,n,c=combat(zone,s);rounds+=n
            savings=s.blade_savings*int('Cave Blade' in p.equipment)
            if deck is not None:
                savings+=(p.sword-1)*s.sword_savings+p.shield*s.shield_savings
                if p.items.get('Bow'): savings+=s.bow_savings
                if p.grenade_armed:
                    p.grenade_armed=False
                    savings+=s.grenade_savings
            cost_to_fight=max(0,c-savings)
            combat_cost+=cost_to_fight
            if deck is not None:
                combat_events.append(dict(action='Combat',target=identity,energy=cost_to_fight,
                                          ranged=bool(p.items.get('Bow'))))
            if c and s.blade_savings and 'Cave Blade' in p.equipment: p.gear_used.add('Cave Blade')
        elif card=='Enhancement':
            bonus+=s.enhance
        elif card=='Item':
            p.items[identity]=p.items.get(identity,0)+1
            items_found.append(identity)
        cards.append(card)
        if deck is not None and card=='Monster':
            ward=4 if s.use_potions and p.potions.get('Ward Potion') else 0
            if combat_cost>p.energy+ward:
                break
    if s.use_potions and held_potion!='Ward Potion' and p.potions.get('Ward Potion') and combat_cost>p.energy+bonus:
        take_potion(p,'Ward Potion');used.append('Ward Potion');combat_cost=max(0,combat_cost-4)
    if s.use_potions and held_potion!='Fortune Potion' and p.potions.get('Fortune Potion') and 'Treasure' in cards:
        take_potion(p,'Fortune Potion');used.append('Fortune Potion');earned+=3
    raw=p.energy-combat_cost+bonus;p.energy=max(0,min(s.cap,raw));p.loot+=earned
    penalty=0;knocked=raw<0
    if knocked:
        penalty=min(max(0,s.lose_loot-s.pack_protection*int('Padded Pack' in p.equipment)),p.loot);p.loot-=penalty
        if penalty<min(s.lose_loot,p.loot+penalty): p.gear_used.add('Padded Pack')
        push=max(0,s.lose_depth-int('Safety Harness' in p.equipment))
        if push<s.lose_depth and zone>push: p.gear_used.add('Safety Harness')
        if push: p.position=p.board.exit(max(0,zone-push))
    found=[];empty_draws=0
    for card in cards:
        if s.potion_chance and p.potion_rng is not None and p.potion_rng.random()<s.potion_chance/100:
            name=p.potion_rng.choice(tuple(POTIONS))
            p.potions[name]=p.potions.get(name,0)+1;found.append(name)
        elif card=='Nothing' and not gate_tonic:
            empty_draws+=1
    if gate_tonic:
        name='Energy Tonic'
        p.potions[name]=p.potions.get(name,0)+1
        found.append(name)
    if deck is not None:
        trim_treasures(p)
        if shovel:
            p.items['Shovel']-=1
            items_used.append('Shovel')
    return record(p,start,s,action,closed,zone=zone,card=' + '.join(cards) if cards else '— (no draw)',
                  potions_found=found,potions_used=used,gate_tonic=gate_tonic,walking_savings=walking_savings,
                  cards=cards,draw_count=len(cards),empty_draws=empty_draws,roll=rolls,monster_hp=(s.hp1,s.hp2,s.hp3)[zone-1] if 'Monster' in cards else 0,
                  monster_attack=(s.atk1,s.atk2,s.atk3)[zone-1] if 'Monster' in cards else 0,
                  rounds=rounds,combat_cost=combat_cost,action_cost=cost,bonus=bonus,raw_energy=raw,
                  loot_change=earned,cache_loot=cache_loot,loot_penalty=penalty,depth_penalty=zone-zone_at(p.position) if knocked else 0,
                  knockdown='Yes' if knocked else 'No',farm_zone=zone if mining else 0,
                  **(dict(drawn=drawn,items_found=items_found,items_used=items_used,
                          combat_events=combat_events) if deck is not None else {}))


def trim_treasures(p):
    """Apply point losses to the lowest-value cards first."""
    p.treasures.sort(reverse=True)
    loss=sum(p.treasures)-p.loot
    while loss>0 and p.treasures:
        value=p.treasures[-1]
        if value<=loss:
            loss-=p.treasures.pop()
        else:
            p.treasures[-1]-=loss
            break


def take_potion(p,name):
    p.potions[name]-=1
    if not p.potions[name]: del p.potions[name]


def drink_tonic(p,s,closed):
    if not s.use_potions or not p.potions.get('Energy Tonic') or p.energy>=s.cap:
        return None
    start=before(p)
    restored=min(s.deep_tonic_energy if s.dice_rules else 3,s.cap-p.energy)
    p.energy+=restored
    take_potion(p,'Energy Tonic')
    return record(p,start,s,'Drink Energy Tonic',closed,bonus=restored,
                  card='Restored energy',potions_used=['Energy Tonic'])


def boss_effect(p,event,s):
    start=before(p);penalty=0;ejected=False;cost=0
    if event['collapse']==1:
        if zone_at(p.position)>0:
            p.killed=True
            penalty=p.loot
            p.loot=0
        return record(p,start,s,'Killed by boss' if p.killed else 'Boss seals entrance',event['closed'],
                      card='d6=%s · Monster boss seals the entrance'%event['die'],
                      boss_roll=event['die'],loot_penalty=penalty)
    if event['collapse'] and zone_at(p.position)>=event['collapse']:
        ejected=True;p.position=p.board.exit(event['collapse']-1)
        harness='Safety Harness' in p.equipment
        penalty=min(max(0,s.boss_loot_loss-2*harness),p.loot);p.loot-=penalty
        cost=min(max(0,s.boss_energy_hit-harness),p.energy);p.energy-=cost
        if harness and (penalty<min(s.boss_loot_loss,p.loot+penalty) or cost<min(s.boss_energy_hit,p.energy+cost)):
            p.gear_used.add('Safety Harness')
    label=('Zone %s collapses'%event['collapse']) if event['collapse'] else 'Boss holds in Zone %s'%event['threatened']
    return record(p,start,s,'Boss ejection' if ejected else 'Boss roll',event['closed'],
                  card='d6=%s · %s'%(event['die'],label),boss_roll=event['die'],
                  boss_zone=event['active_zone'],boss_ejection=ejected,loot_penalty=penalty,action_cost=cost)


def return_turns_needed(p,s,closed):
    """Count future refills needed to walk the return path using permanent gear."""
    path=path_between(p.position,p.board.start,closed,p.board)
    if not path: return None
    energy=p.energy
    refill=s.gain+s.battery_gain*int('Spare Battery' in p.equipment)
    if p.items.get('Energy Canister'): refill+=s.canister_gain
    turns=0
    if s.dice_rules and s.full_energy_moves:
        costs=(1 for _ in range(math.ceil((len(path)-1)/dice_move_reach(p.equipment,s))))
    else:
        costs=(movement_cost(start,end,s,p.equipment,True) for start,end in zip(path,path[1:]))
    for cost in costs:
        if cost>energy:
            if not refill or cost>s.cap: return None
            needed=math.ceil((cost-energy)/refill)
            turns+=needed
            energy=min(s.cap,energy+needed*refill)
        energy-=cost
    return turns


def choose_action(p,s,turn,closed,retreating=False):
    zone=zone_at(p.position)
    if retreating or (not s.adaptive_retreat and turn>=s.retreat_start):
        if zone==0: return ('Extract' if p.visited else 'Rest'),None
        goal=p.board.start;action='Retreat'
    else:
        action='Delve'
        if zone==0:
            if 1 in closed: return ('Extract' if p.visited else 'Rest'),None
            goal=p.board.entrance(1)
        else:
            can_advance=zone<s.max_zone and zone+1 not in closed and turn>=(s.zone2_start if zone==1 else s.zone3_start)
            skip=skips_farm(p,s,zone,closed)
            farms=p.board.farms_in(zone)
            mines=p.board.mines_in(zone)
            if can_advance and (s.route_policy==3 or skip or not (farms or mines)
                                or p.farm_counts[zone]>=s.farm_visits):
                goal=p.board.entrance(zone+1)
            elif skip or (s.route_policy==3 and zone<s.max_zone and p.position!=p.board.exit(zone)):
                goal=p.board.exit(zone)
            else:
                farm=p.board.primary_farm(zone)
                sites=set()
                if s.farm_visits:
                    sites=(set(farms)|set(mines))-p.mined_this_turn
                if zone==3 and s.route_policy==3 and farm is not None and farm not in p.visited:
                    sites={farm}
                if s.route_policy==3 and zone<s.max_zone:
                    sites.intersection_update({p.position})
                if not sites and farm is not None and not s.farm_visits and p.position!=farm and s.route_policy!=3:
                    sites={farm}
                if not sites:
                    return 'Rest',None
                if p.position in sites:
                    return ('Farm' if p.position in farms else 'Mine'),None
                if s.route_policy==0 and farm in sites:
                    goal=farm
                else:
                    goal=min(sites,key=lambda tile:(len(path_between(p.position,tile,closed,p.board)),tile not in farms,tile))
    path=path_between(p.position,goal,tuple(closed),p.board)
    if len(path)<2: return 'Rest',None
    return action,path[1]


@dataclass(frozen=True)
class DecisionChange:
    turn: int
    step: int
    kind: str
    item: str = ''


def run_player(s,rng,boss_schedule=None,potion_seed=None,board=DEFAULT_BOARD,change=None):
    validate(s)
    # Separate loot RNG so discovery chance does not re-roll ordinary cards.
    if potion_seed is None: potion_seed=s.seed+535013
    p=Player(board=board,position=board.start,potion_rng=random.Random(potion_seed));rows=[];closed=()
    priority=PRIORITIES[min(s.gear_priority,3)]
    shop_detour=s.gear_priority==1 or s.route_policy==2
    if s.gear_priority==4 or s.route_policy in (1,3):
        shopper=random.Random(potion_seed+271828)
        preference=shopper.choice(PRIORITIES) if s.gear_priority==4 else priority
        # Comparable players keep the same taste draws when prices change.
        values={name:shopper.uniform(.55,1.8)*(1.4-.075*rank)
                for rank,name in enumerate(preference)}
        priority=sorted(GEAR,key=lambda name:values[name]/(3+getattr(s,GEAR[name][0])),reverse=True)
        shop_detour=shop_detour or (s.gear_priority==4 and preference==PRIORITIES[1])
    schedule=boss_schedule if boss_schedule is not None else boss_timeline(s,random.Random(s.seed+700000003))
    retreating=False
    change_applied=False
    for turn in range(1,s.turns+1):
        if p.escaped or p.killed: break
        carried_energy=p.energy
        income=s.gain+s.battery_gain*int('Spare Battery' in p.equipment)
        p.energy=min(s.cap,p.energy+income)
        if 'Spare Battery' in p.equipment and p.energy>min(s.cap,carried_energy+s.gain):
            p.gear_used.add('Spare Battery')
        step=0
        p.mined_this_turn.clear()
        deferred=set()
        def emit(row):
            nonlocal income,step
            step+=1;row.update(turn=turn,step=step)
            if income:
                row.update(start_energy=carried_energy,gain=income);income=0
            row['boss_zone']=schedule[turn-2]['active_zone'] if turn>1 else 0
            rows.append(row)
        while True:
            if s.adaptive_retreat and not retreating and p.visited:
                needed=return_turns_needed(p,s,closed)
                if needed is None or needed+s.retreat_slack>=s.turns-turn:
                    retreating=True
                    message=('Current gear cannot fund this route with future refills' if needed is None
                             else 'Return needs %s future energy refills'%needed)
                    emit(record(p,before(p),s,'Plan retreat',closed,card=message))
            elif not s.adaptive_retreat and turn>=s.retreat_start:
                retreating=True
            decision=change if change and not change_applied and (turn,step+1)==(change.turn,change.step) else None
            wanted=None
            if not retreating and len(p.equipment)<s.gear_slots:
                # Reserve the next slot and available loot for the highest-priority eligible item.
                wanted=next((name for name in priority if getattr(s,GEAR[name][1]) and name not in p.equipment and name not in deferred
                             and (name!='Climbing Kit' or s.max_zone==3)
                             and (name!='Flashlight' or s.max_zone>=2)),None)
                if decision and decision.kind=='shop' and wanted==decision.item and p.position in board.shops:
                    price=getattr(s,GEAR[wanted][0])
                    if p.loot>=price:
                        deferred.add(wanted)
                        wanted=None
                        change_applied=True
                purchase=buy(p,wanted,s,closed) if wanted and p.position in board.shops else None
                if purchase is not None: emit(purchase);continue
            action,destination=choose_action(p,s,turn,closed,retreating)
            route_goal=''
            if wanted and (shop_detour or board.shop_detours) and p.loot>=getattr(s,GEAR[wanted][0]):
                # A farmer staying on its farm side of a zone needs to visit a vendor.
                vendors=[path_between(p.position,shop,closed,board) for shop in sorted(board.shops)
                         if zone_at(shop)==zone_at(p.position)]
                paths=[path for path in vendors if len(path)>1]
                if paths:
                    action,destination='Delve',min(paths,key=len)[1]
                    route_goal='Shop'
            if decision and decision.kind=='gate' and action=='Delve' and destination is not None:
                if zone_at(destination)>zone_at(p.position) and p.position[1]>0 and p.visited:
                    retreating=True
                    change_applied=True
                    action,destination=choose_action(p,s,turn,closed,retreating)
                    route_goal=''
            if decision and decision.kind=='farm' and action in ('Farm','Mine'):
                change_applied=True
                emit(record(p,before(p),s,'Rest',closed,card='Skipped farming and ended turn'));break
            if decision and decision.kind=='walk' and action=='Delve':
                change_applied=True
                emit(record(p,before(p),s,'Rest',closed,card='Skipped exploration and ended turn'));break
            if action=='Extract':
                start=before(p);p.escaped=True;p.bank+=p.loot;p.loot=0
                emit(record(p,start,s,'Extract',closed));break
            if action=='Rest':
                emit(record(p,before(p),s,'Rest',closed,card='Policy rests; energy carries over'));break
            held=decision.item if decision and decision.kind=='potion' else None
            if held and held!='Energy Tonic':
                change_applied=True
            row=perform(p,s,rng,action,destination,closed,held)
            if row is None:
                if held=='Energy Tonic' and s.use_potions and p.potions.get(held) and p.energy<s.cap:
                    change_applied=True
                    tonic=None
                else:
                    tonic=drink_tonic(p,s,closed)
                if tonic is not None: emit(tonic);continue
                crossing=destination is not None and zone_at(destination)!=zone_at(p.position)
                dark=destination is not None and max(zone_at(destination),zone_at(p.position))>=2 and 'Flashlight' not in p.equipment
                reason='Farm' if action in ('Farm','Mine') else 'Dark gate' if crossing and dark else 'Gate' if crossing else 'Walking'
                emit(record(p,before(p),s,'Wait',closed,card='Insufficient energy for next action',
                            wait_for=reason,route_goal=route_goal));break
            row['route_goal']=route_goal
            emit(row)
            if row['knockdown']=='Yes': break
            if action=='Retreat' and zone_at(p.position)==0:
                start=before(p);p.escaped=True;p.bank+=p.loot;p.loot=0
                emit(record(p,start,s,'Extract',closed));break
        event=schedule[turn-1]
        if event['die'] and not p.escaped:
            row=boss_effect(p,event,s);emit(row);row['boss_zone']=event['active_zone']
        closed=tuple(event['closed'])
    return player_result(p,rows,closed,change_applied)


def player_result(p,rows,closed,change_applied=False):
    return dict(score=p.bank,escaped=int(p.escaped),killed=int(p.killed),depth=zone_at(p.position),
                position=p.position,distance_home=distance_home(p.position,closed,p.board),visited=len(p.visited),carried=p.loot,
                turns=rows[-1]['turn'],knockdowns=sum(r['knockdown']=='Yes' for r in rows),rows=rows,
                equipment=sorted(p.equipment),equipment_spent=sum(r['loot_spent']+r.get('bank_spent',0) for r in rows),
                gear_used=sorted(p.gear_used),
                potions_found=[item for r in rows for item in r['potions_found']],
                potions_used=[item for r in rows for item in r['potions_used']],
                farm_actions=sum(r['action']=='Farm' for r in rows),mine_actions=sum(r['action']=='Mine' for r in rows),
                encounters=sum(r['draw_count'] for r in rows),
                boss_ejections=sum(r['boss_ejection'] for r in rows),
                movement_steps=sum(r.get('move_steps',1) for r in rows
                                   if r['action'] in ('Delve','Retreat')),
                change_applied=change_applied)


def validate(s):
    for name,value in vars(s).items():
        if name in ('treasure_profiles', 'monster_profiles'):
            continue
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value): raise ValueError('%s must be finite.'%name)
        if Settings.__dataclass_fields__[name].type is int and int(value)!=value: raise ValueError('%s must be a whole number.'%name)
    if not 1<=s.turns<=200 or not 1<=s.players<=20 or not 1<=s.runs<=10000: raise ValueError('Turns 1–200, players 1–20, games 1–10,000.')
    if s.seed<0 or not 0<=s.gain<=100 or not 1<=s.cap<=100: raise ValueError('Seed nonnegative; energy gain 0–100; cap 1–100.')
    if not 0<=s.start_energy<=100: raise ValueError('Starting Energy must be 0–100 and is limited by the Energy cap.')
    if not 0<=s.lose_depth<=3 or s.lose_loot<0: raise ValueError('Knockdown zones 0–3; loot penalty nonnegative.')
    if min(s.hp1,s.hp2,s.hp3)<1 or min(s.atk1,s.atk2,s.atk3)<0 or not .5<=s.avg_roll<=100: raise ValueError('HP positive, attacks nonnegative, average roll 0.5–100.')
    if not 1<=s.delve<=20 or not 1<=s.retreat<=20: raise ValueError('Base movement costs must be 1–20; there is no separate step cap.')
    if not 1<=s.zone2_start<=s.zone3_start<=s.turns+1 or not 1<=s.retreat_start<=s.turns+1: raise ValueError('Zone/retreat turn thresholds must be ordered and within turns+1.')
    if s.adaptive_retreat not in (0,1) or not 0<=s.retreat_slack<=10:
        raise ValueError('Retreat mode must be 0 or 1, with 0–10 turns of return slack.')
    if not 1<=s.dark_cost<=10 or not 1<=s.rough_cost<=10: raise ValueError('Terrain multipliers must be 1–10.')
    if not 0<=s.farm_visits<=20 or not 1<=s.farm_cost<=20 or not 1<=s.mine_cost<=20:
        raise ValueError('Mining quota 0–20; activation costs 1–20.')
    if not 0<=s.route_policy<=3 or not all(0<=value<=5 for value in (s.blade_savings,s.pack_protection,s.charm_bonus,s.battery_gain)):
        raise ValueError('Route policy must be 0–3 and equipment bonuses 0–5.')
    if not -1<=s.farm_detour_limit<=60: raise ValueError('Farm detour limit must be -1 (any) or 0–60 steps.')
    if not 1<=s.boss_start<=201 or not 1<=s.boss_threshold<=6: raise ValueError('Boss arrival 1–201; collapse threshold 1–6.')
    if any(v not in (0,1) for v in (s.buy_boots,s.buy_flashlight,s.buy_climbing,s.boss_enabled)): raise ValueError('Equipment and boss switches must be 0 or 1.')
    if min(s.boots_price,s.flashlight_price,s.climbing_price,s.loot_per_depth,s.enhance,s.boss_loot_loss,s.boss_energy_hit)<0: raise ValueError('Prices, rewards and boss penalties cannot be negative.')
    if s.enhance>20: raise ValueError('Enhancement energy must be at most 20.')
    if not 0<=s.deep_cache_loot<=50: raise ValueError('Zone 3 cache treasure must be 0–50.')
    if not 0<=s.gear_slots<=10 or not 0<=s.gear_priority<=len(PRIORITIES) or not 1<=s.max_zone<=3:
        raise ValueError('Equipment slots 0–10, shopping priority 0–4, deepest zone 1–3.')
    if not 0<=s.potion_chance<=100 or s.use_potions not in (0,1):
        raise ValueError('Potion chance 0–100 and auto-use 0 or 1.')
    if s.deep_entry_tonic not in (0,1): raise ValueError('Zone 3 entrance Energy Tonic must be 0 or 1.')
    if not (0<=s.farm_shared_limit<=20 and 1<=s.deep_tonic_energy<=10
            and 2<=s.boots_move_range<=6 and 1<=s.shield_block_per_level<=3):
        raise ValueError('Shared farm uses 0–20; Tonic Energy 1–10; Boots reach 2–6; Shield block 1–3.')
    if s.shared_decks not in (0,1): raise ValueError('Shared zone decks must be 0 or 1.')
    if s.dice_rules not in (0,1) or s.dice_rules and not s.shared_decks:
        raise ValueError('Dice rules require shared zone decks.')
    if s.dice_rules and s.cap>10:
        raise ValueError('Dice rules cap Energy at 10.')
    if s.player_duels not in (0, 1) or s.moving_boss not in (0, 1):
        raise ValueError('Player duels and moving boss must be 0 or 1.')
    if (s.player_duels or s.moving_boss) and not s.dice_rules:
        raise ValueError('Player duels and the moving boss require Dice rules.')
    if s.rolled_enemy_attacks not in (0, 1) or s.rolled_enemy_attacks and not s.dice_rules:
        raise ValueError('Rolled enemy attacks require Dice rules and must be 0 or 1.')
    if not 1 <= s.boss_challenge_pct <= 100:
        raise ValueError('Minimum bot boss win chance must be 1–100%.')
    validate_profiles(s.monster_profiles)
    if not (1 <= s.boss_hp <= 100 and 0 <= s.boss_attack <= 20 and 1 <= s.boss_hoard <= 100):
        raise ValueError('Boss HP and hoard must be 1–100 and attack must be 0–20.')
    for zone in (1,2,3):
        if not 1<=getattr(s,f'hp_min{zone}')<=getattr(s,f'hp_max{zone}')<=100:
            raise ValueError('Monster HP range must be ordered and between 1 and 100.')
        if not 0<=getattr(s,f'treasure_min{zone}')<=getattr(s,f'treasure_max{zone}')<=50:
            raise ValueError('Treasure range must be ordered and between 0 and 50.')
    if not isinstance(s.treasure_profiles,dict) or set(s.treasure_profiles)-{'1','2','3'}:
        raise ValueError('Exact treasure profiles require zone keys 1, 2 or 3.')
    if s.treasure_profiles and not s.dice_rules:
        raise ValueError('Exact treasure profiles require Dice rules.')
    gold_values={str(n) for n in range(51)}
    for zone,profile in s.treasure_profiles.items():
        if (not isinstance(profile,dict) or len(profile)>51
                or any(value not in gold_values or type(count) is not int
                       or not 1<=count<=50 for value,count in profile.items())):
            raise ValueError('Use gold values 0–50 and positive whole-number card counts.')
        if sum(profile.values())!=getattr(s,f'deck_treasures{zone}'):
            raise ValueError(f'Zone {zone} exact counts must sum to its Treasure count.')
    if not all(0<=value<=20 for value in (s.sword_price,s.shield_price,s.bounty1,s.bounty2,s.bounty3)):
        raise ValueError('Dice prices and bounties must be between 0 and 20.')
    if s.field_starter_gear not in (0,1) or not 0<=s.sword_damage_bonus<=3:
        raise ValueError('Field starter gear must be 0 or 1 and extra Sword damage must be 0–3.')
    if any(value not in (0,1) for value in (s.shop_gold_prices,s.full_energy_moves)):
        raise ValueError('Gold shop prices and full Energy moves must be 0 or 1.')
    if not all(0<=getattr(s,key)<=20 for key in ('sword_savings','shield_savings','upgrade_price',
                'bow_savings','grenade_savings','canister_gain','energy_potion_gain')):
        raise ValueError('Zone deck balance values must be between 0 and 20.')
    for price, enabled in GEAR.values():
        if getattr(s,price)<0 or getattr(s,enabled) not in (0,1):
            raise ValueError('Gear prices must be nonnegative and purchase switches must be 0 or 1.')
    if min(s.p_treasure,s.p_monster,s.p_enhance)<0 or sum((s.p_treasure,s.p_monster,s.p_enhance))>100.00001: raise ValueError('Card chances must be nonnegative and total at most 100%.')
