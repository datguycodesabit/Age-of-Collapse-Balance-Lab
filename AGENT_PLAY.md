# Playing a match with separate agents

Run commands from the repository root with Python 3. No packages or web server
are needed. Seats are zero-based. Give each agent one seat and a shared absolute
state-file path. The simulator owns all state; agents choose commands.

Create a match with four players and existing balance defaults:

```sh
python3 outputs/local_web_simulator/agent_cli.py create --state /tmp/aoc-match.json
```

For two players or another setup, write a configuration file containing
`{"settings":{"players":2,"seed":42}}` and add `--config /tmp/aoc-config.json`.
Configuration can also contain `board` in the web lab's exported layout format.
Existing saves cannot be overwritten with `create`.

Pass `--dice-rules` on create to use the viewer defaults. In dice mode,
`Move` has only a destination. `Mine` draws only at marked sites, or takes
a rock destination when clearing an adjacent rock in the same zone.
A regular mine or rock clear costs 1 Energy and a farm costs 2 Energy.
The default starting pool and later round refill are both 2, and can be
set independently under `settings` in the create config. For example,
`{"settings":{"start_energy":3,"gain":2}}` gives 3 Energy in round one
and adds 2 at the start of each subsequent round, up to the cap.
Combat exchanges appear in `combat_events`, and reaching the Surface Exit
automatically banks the carried hand without ending the run. Your
observation includes `bank_cards` for shop spending.
With `shop_gold_prices: 1`, shops charge gold value. They spend carried
Treasure first, then banked Treasure, and keep any leftover gold on the
card. The no-cache preset uses this mode.
With `full_energy_moves: 1`, a Move costs 1 Energy and can travel up to
two squares or four with Boots. Choose a legal destination. The resolver
follows a shortest path and reports the traveled squares in `move_path`.

Pass `--shared-decks` for the earlier automatic combat model using the same
three 50-card decks.
In that mode the CLI offers `Move` with a destination, optionally with
`"retreat":true` for a step toward Surface without a discovery, and `Mine`
at either type of mining site. Combat happens immediately when a Monster
is drawn and appears in the action's `combat_events`. The commands
`Buy`, `Use`, `Tonic`, `EndTurn` and `Extract` appear when available.
`Use Pickaxe` reveals private `pick_options` and the next `Mine` selects the
card by zero-based index from the legal actions. Read `deck_remaining` to
see shared supply without revealing its order.

Read your observation:

```sh
python3 outputs/local_web_simulator/agent_cli.py observe --state /tmp/aoc-match.json --actor 0
```

If `active_actor` equals your seat, choose an object from `legal_actions` and
submit it with the current revision:

```sh
python3 outputs/local_web_simulator/agent_cli.py act --state /tmp/aoc-match.json --actor 0 \
  --command '{"actor":0,"revision":0,"action":{"kind":"Delve","destination":[0,1]}}'
```

Commands can instead come from stdin. `--actor` selects the observation seat;
the command's `actor` identifies the acting seat. Responses contain `result` and
`observation`. Exit codes: 0 success, 2 rejected command, 1 file/config error.
Rejections preserve the save, revision, Energy, loot and all random streams.
Refresh the observation after `stale_revision`.

## Combat playtest

Create a match with the combat preset from the repository root.

```sh
python3 outputs/local_web_simulator/agent_cli.py create --state /tmp/aoc-combat.json \
  --config outputs/local_web_simulator/playtests/rolled_combat_playtest.json
```

Select an offered `{"kind":"AttackPlayer","target":1}` to challenge the
adjacent seat, or `{"kind":"AttackBoss"}` to challenge the boss at its gate.
Both cost 1 Energy and require Energy left after payment. A duel ends when a
player reaches zero Energy. The loser hands all carried Treasure to the
winner and forfeits the rest of the round. Both players see the duel exchanges
in their logs. The boss heals if it knocks its challenger down.

In the rolled preset, each Monster profile has an archetype, fixed HP, and
six damage faces. A surviving enemy rolls a separate d6 after the player's
strike. Combat exchange logs include `enemy_roll`, `raw_attack`,
`shield_absorbed`, and `energy_lost`. A null `enemy_roll` means the player
landed the killing blow. The fixed-counter preset remains available as
`playtests/combat_playtest.json`.

`boss` shows the current gate, HP, counterattack, hoard, and next advance odds.
`boss_events` shows rolls that already happened. A boss kill makes `complete`
true immediately and sets `boss_defeated_by` to the killer's seat. The killer
gets the banked hoard and qualifies for scoring with living players on
Surface. Use `winners` for the final result.

## Coordinator loop

1. Create one match. Assign one agent per seat and provide this document and
   the state path. Only the coordinator reads the save file itself.
2. Read an observation and dispatch the active seat. The agent can issue
   several commands per turn. Every accepted command advances the revision.
3. `EndTurn`, `Extract`, or a monster knockdown hands off to the next active
   seat. A duel loser also loses any remaining turn that round. Inactive
   agents should wait for dispatch instead of repeatedly polling.
4. After all living, unextracted seats finish, the simulator resolves one shared
   boss roll, advances the round, refills Energy once and resets mining limits.
5. Stop at `complete`. Record `standings` and `winners`. The configured final
   round is a hard deadline. If an agent cannot continue, the coordinator can
   submit `EndTurn` for its seat using the current revision.

Suggested player-agent prompt:

> You play seat SEAT in the Python cave simulator. Use agent_cli.py and state
> file STATE. Maximize your chance of winning by banked treasure. Read only your
> seat's observation. On your turn choose from legal_actions, submit with the
> latest revision, and continue until active_actor changes or complete is true.
> Return a brief handoff with your last revision and decision rationale. Do not
> read or edit the save, simulator code, or another seat's observations. Do not
> run another player's commands. Preserve your strategy between turns.

## Earlier independent-draw rules

Escapees compete on banked treasure; ties share first. No escapees means no
winner. The layout and boss rolls are shared. Encounters, visited tiles, mines,
loot and potion streams are per-player. There is no player combat, blocking,
shared loot depletion or limited shop stock.

`Delve` walks to an adjacent tile and draws on its first underground visit.
`Retreat` must reduce shortest distance home and draws no cards. There is no
step cap; Energy and zone-opening turns restrict movement. `Extract` banks loot
on Surface after a cave visit and permanently ends that player's run. Extraction
is explicit when returning to Surface. `Farm` and `Mine` allow one paid
activation per site per turn. `Buy` trades carried loot at a shop. `Tonic` spends
an Energy Tonic charge. Other potions follow the existing automatic policy,
controlled by `use_potions`. `EndTurn` carries remaining Energy forward.

With `deep_entry_tonic` enabled, the first discovery at the Zone 3 gate
adds one Energy Tonic to your inventory after the encounter. Use `Tonic`
on a later action to restore up to 3 Energy. The normal discovery card and
its random potion roll still resolve.

Built-in AI route, shopping, farming quota and retreat preferences are visible
in settings for context but do not constrain agent decisions. Gear switches,
slots, prices, costs, odds and zone-opening turns still apply.

Observations contain legal actions, your private loot/potions/visited tiles/log,
public positions/Energy/gear/bank, and resolved boss rolls. They omit the seed,
future boss rolls, RNG states and opponents' private logs. Agents with filesystem
access are trusted to honor seat assignments; this is local orchestration,
not isolation against hostile agents.

## Persistence and Python interface

The state file is a versioned settings/layout/accepted-command journal. Loading
replays it to recover exact RNG positions and implicit round transitions. Keep
the simulator version with the save; incompatible rule changes must bump the
save/protocol version. File locking serializes CLI processes on macOS/Linux,
and atomic replacement protects the previous save if a write is interrupted.
The `.lock` sibling is retained. Do not edit the journal manually.

In-process coordinators can use `AgentMatch(settings, board)`, `observation(seat)`,
`submit(command)`, `serialize()` and `AgentMatch.restore(data)`. Serialize calls
yourself in-process; the CLI supplies process locking. No sub-agents launch
automatically.
