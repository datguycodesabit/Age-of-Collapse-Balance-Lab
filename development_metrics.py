"""Balance diagnostics derived from accepted actions, without changing play."""
from collections import Counter
from math import ceil
from statistics import mean, median

from model import zone_at


def average(values):
    return mean(values) if values else None


class DevelopmentMetrics:
    def __init__(self, settings):
        self.settings = settings
        self.first_banks = []
        self.entry_rounds = {zone: [] for zone in (1, 2, 3)}
        self.mine_rounds = {zone: [] for zone in (1, 2, 3)}
        self.banked_after_mining = Counter()
        self.qualified_after_mining = Counter()
        self.regular_miners = 0
        self.deck_left = {}
        self.energy = Counter(dict(walking=0, mining=0, combat=0, collapse=0))
        self.outcomes = Counter(dict(scored=0, surface_zero=0, underground=0, boss=0))
        self.forfeited_bank = 0
        self.purchases = {item: [] for item in ('Sword', 'Shield', 'Boots')}
        self.uses = Counter()

    def record_player(self, game, player):
        rows = player['rows']
        entered, mined = {}, {}
        first_bank = None
        banked_zones = set()
        regular_mined = False
        purchases, used = {}, set()
        for row in rows:
            turn, action = row['turn'], row['action']
            for zone in (row['zone'], *(zone_at(tile) for tile in row.get('move_path', ()))):
                if zone:
                    entered.setdefault(zone, turn)
            if row.get('banked_now') or action=='Extract' and row['bank']>0:
                banked_zones.update(mined)
                if first_bank is None:
                    first_bank = turn
                    self.first_banks.append(turn)
            if row['farm_zone'] and row['draw_count']:
                mined.setdefault(row['farm_zone'], turn)
                regular_mined |= action=='Mine'
            if self.settings.shared_decks and 'deck_remaining' in row:
                left = self.deck_left.setdefault(game, {1: 50, 2: 50, 3: 50})
                for zone, count in row['deck_remaining'].items():
                    left[int(zone)] = min(left[int(zone)], count)
            if action in ('Delve', 'Retreat'):
                self.energy['walking'] += row['action_cost']
            elif action in ('Mine', 'Farm', 'Mine rock'):
                self.energy['mining'] += row['action_cost']
            elif row['boss_ejection']:
                self.energy['collapse'] += row['action_cost']
            combat = row['combat_cost']
            if self.settings.dice_rules:
                # A fatal counterattack can exceed the Energy actually lost.
                combat = min(combat, max(0, row['start_energy']-row['action_cost']))
                if action in ('Buy Sword', 'Buy Shield', 'Buy Boots'):
                    item = action[4:]
                    spend = row['loot_spent']+row.get('bank_spent', 0)
                    if item not in purchases:
                        purchases[item] = (turn, spend)
                for fight in row.get('combat_events', ()):
                    for exchange in fight['exchanges']:
                        if exchange['weapon']:
                            used.add('Sword')
                        if exchange['shield_absorbed']:
                            used.add('Shield')
            self.energy['combat'] += combat
        for zone, turn in entered.items():
            self.entry_rounds[zone].append(turn)
        for zone, turn in mined.items():
            self.mine_rounds[zone].append(turn)
        self.banked_after_mining.update(banked_zones)
        if player['escaped']:
            self.qualified_after_mining.update(banked_zones)
        self.regular_miners += regular_mined
        if 'Boots' in player['gear_used']:
            used.add('Boots')
        for item, purchase in purchases.items():
            self.purchases[item].append(purchase)
            if item in used:
                self.uses[item] += 1
        if player['escaped']:
            outcome = 'scored' if player['score'] else 'surface_zero'
        else:
            outcome = 'boss' if player['killed'] else 'underground'
            self.forfeited_bank += rows[-1]['bank']
        self.outcomes[outcome] += 1
        return first_bank

    def report(self, players, games):
        zones = []
        for zone, entries in self.entry_rounds.items():
            mines = self.mine_rounds[zone]
            row = dict(zone=zone, entered=len(entries), entry_round=average(entries),
                       mined=len(mines), mine_round=average(mines),
                       banked_after_mining=self.banked_after_mining[zone],
                       qualified_after_mining=self.qualified_after_mining[zone])
            if self.settings.shared_decks:
                draws = [50-left.get(zone, 50) for left in self.deck_left.values()]
                draws += [0]*(games-len(draws))
                draws.sort()
                row.update(draws=mean(draws), p95_draws=draws[ceil(.95*games)-1],
                           left=50-mean(draws), exhausted=draws.count(50))
            zones.append(row)
        gear = []
        if self.settings.dice_rules:
            for item, receipts in self.purchases.items():
                gear.append(dict(item=item, bought=len(receipts), used=self.uses[item],
                                 round=average([turn for turn,_ in receipts]),
                                 gold=average([price for _,price in receipts])))
        return dict(zones=zones, gear=gear, first_bank_median=median(self.first_banks) if self.first_banks else None,
                    regular_miners=self.regular_miners,
                    first_bank_timeline=[sum(bank<=turn for bank in self.first_banks)
                                         for turn in range(1,self.settings.turns+1)],
                    unqualified_bank=self.forfeited_bank/players, outcomes=dict(self.outcomes),
                    energy={key: total/players for key,total in self.energy.items()})
