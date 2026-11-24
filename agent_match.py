"""Run shared rounds, validate commands, and replay accepted commands from saves."""
import copy
import random
from dataclasses import asdict

from engine import board_from, board_metadata, settings_from
from model import (GEAR, GEAR_EFFECTS, POTIONS, Player, affordable_step, before, boss_advance_threshold,
                   boss_effect, boss_timeline, buy, distance_home, drink_tonic, moving_boss_round, neighbors,
                   perform, record, trim_treasures, zone_at)
import zone_decks
import dice_rules
from enemy_profiles import boss_faces


class AgentMatch:
    """Authoritative shared rounds. Saves are versioned deterministic command journals."""

    VERSION = 5

    def __init__(self, settings=None, board=None):
        self.settings = settings_from(settings or {})
        self.board = board_from(board)
        self.initial_board = self.board
        settings = self.settings
        seat_seeds = [settings.seed + seat * 104729 for seat in range(settings.players)]
        # Separate streams keep potion and combat rolls independent of other draws.
        self.players = [
            Player(board=self.board, position=self.board.start,
                   potion_rng=random.Random(seed + 535013))
            for seed in seat_seeds
        ]
        self.rngs = [random.Random(seed) for seed in seat_seeds]
        if settings.dice_rules:
            self.decks = dice_rules.decks(settings)
            self.combat_rngs = [random.Random(seed + 93772619) for seed in seat_seeds]
        elif settings.shared_decks:
            self.decks = zone_decks.shuffled_decks(settings.seed)
        else:
            self.decks = None
        self.boss_rng = random.Random(settings.seed + 700000003)
        self._schedule = [] if settings.moving_boss else boss_timeline(settings, self.boss_rng)
        self.boss_defeated_by = None
        self.boss_combat_rng = random.Random(settings.seed + 431154793)
        self.duel_rng = random.Random(settings.seed + 503663093)
        self.round = 1
        self.active = 0
        self.revision = 0
        self.complete = False
        self.closed = ()
        self.forfeited = set()
        self.farm_uses = {}
        self.journal = []
        self.boss_events = []
        self.logs = [[] for _ in self.players]
        if settings.dice_rules:
            for player in self.players:
                player.sword = 0
                player.energy = min(settings.cap, settings.start_energy)
        else:
            self._refill()

    def _refill(self):
        s = self.settings
        self.farm_uses.clear()
        self.forfeited.clear()
        for p in self.players:
            if p.escaped or p.killed:
                continue
            previous = p.energy
            canister = s.canister_gain if p.items.get('Energy Canister') else 0
            p.energy = min(s.cap, p.energy+s.gain+canister+s.battery_gain*int('Spare Battery' in p.equipment))
            if p.energy > min(s.cap, previous+s.gain):
                p.gear_used.add('Spare Battery')
            p.mined_this_turn.clear()

    def _advance(self):
        """Give the next seat a turn, or close the round after the last seat."""
        remaining_seats = [seat for seat, player in enumerate(self.players)
                           if not player.escaped and not player.killed]
        if not remaining_seats:
            self._finish()
            return

        next_seat = next((seat for seat in remaining_seats if seat > self.active and seat not in self.forfeited), None)
        if next_seat is not None:
            self.active = next_seat
            return

        self._resolve_round_boss()
        # The boss can remove seats before the next round starts.
        first_seat = next((seat for seat, player in enumerate(self.players)
                           if not player.escaped and not player.killed), None)
        if self.round == self.settings.turns or first_seat is None:
            self._finish()
            return

        self.round += 1
        self._refill()
        self.active = first_seat

    def boss_status(self, roll_round=None):
        s = self.settings
        if (not s.moving_boss or not s.boss_enabled or self.round < s.boss_start
                or 1 in self.closed or self.complete or self.boss_defeated_by is not None):
            return None
        zone = 3 - len(self.closed)
        roll_round = self.round if roll_round is None else roll_round
        threshold = boss_advance_threshold(s, roll_round) if roll_round <= s.turns else None
        result = dict(zone=zone, tile=self.board.entrance(zone), hp=s.boss_hp,
                    attack=s.boss_attack, hoard=s.boss_hoard,
                    roll_round=roll_round if threshold else None, threshold=threshold,
                    advance_chance=(7-threshold)/6 if threshold else None)
        if s.rolled_enemy_attacks:
            result['attack_faces'] = boss_faces(s)
        return result

    def _resolve_round_boss(self):
        if self.settings.moving_boss:
            event = moving_boss_round(self.settings, self.boss_rng, self.round, self.closed)
            if event['die']:
                event['tile_before'] = self.board.entrance(event['threatened'])
                zone = event['active_zone']
                event['tile_after'] = self.board.entrance(zone) if zone else None
            self._schedule.append(event)
        else:
            event = self._schedule[self.round - 1]
        self.closed = tuple(event['closed'])
        if event['die']:
            self.boss_events.append(copy.deepcopy(event))
            for seat, player in enumerate(self.players):
                if player.escaped or player.killed:
                    continue
                if self.settings.dice_rules:
                    row = dice_rules.resolve_boss(self, player, event)
                else:
                    row = boss_effect(player, event, self.settings)
                    if self.decks is not None:
                        trim_treasures(player)
                row['turn'] = self.round
                if self.settings.moving_boss:
                    row.update(boss=self.boss_status(self.round + 1), boss_event=event)
                self.logs[seat].append(row)

    def _finish(self):
        self.complete = True
        if self.settings.dice_rules:
            for seat, player in enumerate(self.players):
                player.escaped = not player.killed and (zone_at(player.position) == 0
                                                        or seat == self.boss_defeated_by)
        self.active = None

    def _execute(self, p, rng, action):
        """Single model action; called on copies when enumerating legal commands."""
        s = self.settings
        kind = action.get('kind')
        if kind == 'AttackBoss':
            return dice_rules.attack_boss(self, p, self.boss_combat_rng)
        if s.dice_rules and kind in ('Move','Mine','Use','Buy'):
            return dice_rules.resolve(self,p,rng,action)
        if self.decks is not None and kind in ('Move','Mine','Use','Buy'):
            return zone_decks.execute(self,p,rng,action)
        if kind in ('Delve', 'Retreat'):
            destination = action.get('destination')
            if (not isinstance(destination, list) or len(destination) != 2
                    or any(type(v) is not int for v in destination)):
                return None
            destination = tuple(destination)
            zone = zone_at(destination)
            if zone > zone_at(p.position):
                if zone == 2 and self.round < s.zone2_start or zone == 3 and self.round < s.zone3_start:
                    return None
            if kind == 'Retreat' and distance_home(destination, self.closed, self.board) >= distance_home(p.position, self.closed, self.board):
                return None
            return perform(p, s, rng, kind, destination, self.closed)
        if kind in ('Farm', 'Mine'):
            return perform(p, s, rng, kind, closed=self.closed)
        if kind == 'Buy':
            return buy(p, action.get('item'), s, self.closed)
        if kind == 'Tonic':
            return drink_tonic(p, s, self.closed)
        if kind == 'Extract' and zone_at(p.position) == 0 and p.visited:
            start = before(p)
            p.escaped = True
            p.bank += p.loot
            p.loot = 0
            p.treasures.clear()
            return record(p, start, s, 'Extract', self.closed)
        if kind == 'EndTurn':
            return record(p, before(p), s, 'Rest', self.closed)
        return None

    def _shared_step_allowed(self,p,action):
        destination = tuple(action['destination'])
        zone = zone_at(destination)
        if zone>zone_at(p.position):
            if zone==2 and self.round<self.settings.zone2_start or zone==3 and self.round<self.settings.zone3_start:
                return None
        retreat = action.get('retreat',False)
        if retreat and distance_home(destination,self.closed,self.board)>=distance_home(p.position,self.closed,self.board):
            return False
        return affordable_step(p,self.settings,destination,retreat) is not None

    def _shared_move(self,p,rng,action,deck):
        kind='Retreat' if action.get('retreat') else 'Delve'
        return perform(p,self.settings,rng,kind,tuple(action['destination']),self.closed,deck=deck)

    def legal_actions(self, actor):
        if self.complete or actor != self.active:
            return []
        if self.settings.dice_rules:
            return dice_rules.legal(self,actor)
        if self.decks is not None:
            return zone_decks.legal(self,actor)
        p = self.players[actor]
        candidates = [{'kind': kind, 'destination': list(tile)}
                      for tile in sorted(neighbors(p.position, self.closed, self.board))
                      for kind in ('Delve', 'Retreat')]
        candidates += [{'kind': kind} for kind in ('Farm', 'Mine', 'Tonic', 'Extract', 'EndTurn')]
        candidates += [{'kind': 'Buy', 'item': item} for item in GEAR]
        return [action for action in candidates
                if self._execute(copy.deepcopy(p), copy.deepcopy(self.rngs[actor]), action) is not None]

    def submit(self, command):
        """Validate against the current turn before spending Energy or randomness."""
        reason = None
        if not isinstance(command, dict) or set(command) != {'actor', 'revision', 'action'}:
            reason = 'invalid_command'
        elif type(command['revision']) is not int or command['revision'] != self.revision:
            reason = 'stale_revision'
        elif self.complete:
            reason = 'match_complete'
        elif type(command['actor']) is not int or command['actor'] != self.active:
            reason = 'wrong_actor'
        elif not self._valid_action_shape(command['action']) or command['action'] not in self.legal_actions(self.active):
            reason = 'illegal_action'
        if reason:
            return dict(accepted=False, reason=reason, revision=self.revision)
        return self._commit(command)

    def _commit(self,command):
        """Apply a command checked against the current legal action list."""
        actor = self.active
        action = command['action']
        if action['kind'] == 'AttackPlayer':
            target = action['target']
            row, defense = dice_rules.duel(self, actor, target)
            if defense['knockdown'] == 'Yes':
                self.forfeited.add(target)
            self._log_action(target, defense)
        else:
            row = self._execute(self.players[actor], self.rngs[actor], action)
        if row.get('boss_defeated'):
            self.boss_defeated_by = actor
            self._finish()
            row['escaped'] = 'Yes'
            for seat, player in enumerate(self.players):
                if seat != actor and not player.killed:
                    self._log_action(seat, record(
                        player, before(player), self.settings, 'Boss defeated', self.closed,
                        card=f'Player {actor + 1} defeated the boss and banked the hoard'))
        self._log_action(actor, row)
        self.journal.append(copy.deepcopy(command))
        self.revision += 1
        if not self.complete and (action['kind'] in ('EndTurn', 'Extract') or row['knockdown'] == 'Yes'):
            self._advance()
        return dict(accepted=True, reason='ok', revision=self.revision, event=copy.deepcopy(row))

    def _log_action(self, actor, row):
        row['turn'] = self.round
        if self.decks is not None:
            row['deck_remaining'] = {zone:len(cards) for zone,cards in self.decks.items()}
            row['sword']=self.players[actor].sword
            row['shield']=self.players[actor].shield
        if self.settings.moving_boss:
            row['boss'] = self.boss_status()
        self.logs[actor].append(row)

    @staticmethod
    def _valid_action_shape(action):
        if not isinstance(action, dict) or not isinstance(action.get('kind'), str):
            return False
        if action['kind'] in ('Delve', 'Retreat'):
            destination = action.get('destination')
            return (set(action) == {'kind', 'destination'} and isinstance(destination, list)
                    and len(destination) == 2 and all(type(v) is int for v in destination))
        if action['kind'] == 'Buy':
            return set(action) == {'kind', 'item'} and isinstance(action.get('item'), str)
        if action['kind'] == 'AttackPlayer':
            return set(action) == {'kind', 'target'} and type(action['target']) is int
        if action['kind'] == 'Mine' and 'pick' in action:
            return set(action)=={'kind','pick'} and type(action['pick']) is int
        if action['kind']=='Mine' and 'destination' in action:
            tile=action['destination']
            return set(action)=={'kind','destination'} and isinstance(tile,list) and len(tile)==2 and all(type(n) is int for n in tile)
        if action['kind'] in ('Move','Use'):
            if 'destination' in action:
                dest=action['destination']
                if not isinstance(dest,list) or len(dest)!=2 or any(type(v) is not int for v in dest):
                    return False
            if 'target' in action and type(action['target']) is not int:
                return False
            if 'retreat' in action and type(action['retreat']) is not bool:
                return False
            return True
        return set(action) == {'kind'}

    def observation(self, actor):
        if type(actor) is not int or not 0 <= actor < len(self.players):
            raise ValueError('Unknown player seat.')
        p = self.players[actor]
        public = [dict(actor=i, position=list(other.position), energy=other.energy,
                       equipment=sorted(other.equipment), escaped=other.escaped,
                       killed=other.killed, bank=other.bank)
                  for i,other in enumerate(self.players)]
        survivors = [i for i,p in enumerate(self.players) if p.escaped]
        best = max((self.players[i].bank for i in survivors), default=None)
        observation = dict(protocol_version=1, revision=self.revision, round=self.round,
                    active_actor=self.active, complete=self.complete, closed=list(self.closed),
                    settings={k:v for k,v in asdict(self.settings).items() if k != 'seed'},
                    board=board_metadata(self.board), players=public,
                    you=dict(actor=actor, loot=p.loot, potions=dict(p.potions),
                             visited=[list(t) for t in sorted(p.visited)],
                             mined_this_turn=[list(t) for t in sorted(p.mined_this_turn)],
                             distance_home=distance_home(p.position,self.closed,self.board)),
                    legal_actions=self.legal_actions(actor),
                    your_log=copy.deepcopy(self.logs[actor]), boss_events=copy.deepcopy(self.boss_events),
                    catalog=copy.deepcopy(dict(gear=GEAR_EFFECTS, potions=POTIONS)),
                    standings=sorted(public, key=lambda item: (not item['escaped'], -item['bank'], item['actor'])) if self.complete else [],
                    winners=[i for i in survivors if self.players[i].bank == best] if self.complete else [])
        if self.decks is not None:
            for other,state in zip(public,self.players):
                other.update(sword=state.sword,shield=state.shield)
            zone=zone_at(p.position)
            observation['you'].update(items={name:count for name,count in p.items.items() if count},
                                      treasures=p.treasures.copy(),grenade_armed=p.grenade_armed,
                                      pick_options=copy.deepcopy(self.decks[zone][:2]) if p.pick_pending else [])
            observation['deck_remaining']={zone:len(pile) for zone,pile in self.decks.items()}
            observation['catalog']['items']=zone_decks.ITEMS.copy()
        if self.settings.dice_rules:
            observation['you']['bank_cards']=p.bank_cards.copy()
            if self.settings.farm_shared_limit:
                observation['farm_uses_this_round']=[dict(position=tile,uses=uses)
                                                     for tile,uses in sorted(self.farm_uses.items())]
            observation['catalog']['potions']['Energy Tonic']=(
                f'Restore up to {self.settings.deep_tonic_energy} Energy.')
            if self.settings.full_energy_moves:
                observation['catalog']['gear']['Boots']=f'Move up to {self.settings.boots_move_range} squares for 1 Energy.'
                observation['catalog']['items']['Speed Potion']='Single use. Double the range of your next move.'
            if self.settings.shop_gold_prices:
                observation['catalog']['items']['Coupon']='Permanent. Reduce the gold cost of each purchase by 1.'
        if self.settings.moving_boss:
            observation.update(boss=self.boss_status(), boss_defeated_by=self.boss_defeated_by)
        if self.settings.player_duels:
            observation['forfeited_this_round'] = sorted(self.forfeited)
        return observation

    def serialize(self):
        # Replay preserves every RNG stream and implicit round transition, without pickle.
        return dict(version=self.VERSION, settings=asdict(self.settings),
                    board=board_metadata(self.initial_board)['layout'], commands=copy.deepcopy(self.journal))

    @classmethod
    def restore(cls, data):
        if not isinstance(data, dict) or set(data) != {'version', 'settings', 'board', 'commands'}:
            raise ValueError('Invalid match save.')
        if type(data['version']) is not int or data['version'] not in (1, 2, 3, 4, cls.VERSION) or not isinstance(data['commands'], list):
            raise ValueError('Unsupported match save version or journal.')
        if not isinstance(data['settings'], dict) or not isinstance(data['board'], dict):
            raise ValueError('Match save requires settings and a board.')
        # Older journals recorded the attack value but had no entrance reward.
        settings = {'deep_entry_tonic': 0, **data['settings']}
        if data['version'] < 3 and settings.get('dice_rules'):
            for zone, counts in zone_decks.COMPOSITION.items():
                settings[f'deck_monsters{zone}'] = counts['Monster']
                settings[f'deck_treasures{zone}'] = counts['Treasure']
        if data['version'] == 1 and settings.get('dice_rules'):
            settings['start_energy'] = settings.get('gain', dice_rules.DEFAULTS['gain'])
            settings['mine_cost'] = settings.get('mine_cost', 2)
            settings['farm_cost'] = settings['mine_cost']
        match = cls(settings, data['board'])
        for command in data['commands']:
            if not match.submit(command)['accepted']:
                raise ValueError('Invalid command in match journal.')
        return match
