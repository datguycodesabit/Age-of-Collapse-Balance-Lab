# Age of Collapse Balance Lab

From this folder run `python3 server.py`, then open http://localhost:8765.

## Read the simulator code

Start with a small run of the viewer's five-seat preset. From this folder,
run the following in a shell. It prints the average qualifying score across
three games, then the opening actions from the first seat's replay.

```sh
python3 - <<'PY'
import json
from pathlib import Path

from engine import board_from, experiment, settings_from

preset = json.loads(Path('playtests/deep_upside_no_cache.json').read_text())
settings = settings_from({**preset['settings'], 'runs': 3, 'seed': 42})
report = experiment(settings, board=board_from(preset['board']), sample_limit=1)

print('Average qualifying score', report['metrics']['avg_score'])
for event in report['samples'][0]['rows'][:8]:
    print(event['turn'], event['action'], event['position_out'], event['end_energy'])
PY
```

Follow one action through the code in this order.

1. [`engine.py`](engine.py) uses `experiment()` to run games and summarize the
   results. In shared-deck modes, `shared_game()` opens one `AgentMatch` per
   game and asks the bot policy to choose from the active seat's legal actions.
2. [`agent_match.py`](agent_match.py) owns the players, shared decks, and turn
   order. `submit()` checks the actor, revision, and action. `_commit()` records
   each accepted action, then advances the turn after an end-turn command,
   extraction, or knockdown. `_advance()` resolves the boss after the last seat
   finishes and starts the next round if the match is still going.
3. [`dice_rules.py`](dice_rules.py) resolves the current Dice mode. Read `move()`
   to see how a paid move follows a path and banks at the Surface Exit. Read
   `mine()` to see how a draw can call `fight()` and how defeat leaves the rest
   of the batch in the deck. [`model.py`](model.py) defines the board, settings,
   player state, and shared replay fields. [`zone_decks.py`](zone_decks.py)
   supplies the shuffled decks and the earlier shared-deck rules.

Run `python3 -m unittest test_dice_rules test_agent_match` from this folder
to see examples of legal and rejected commands, round transitions, and save replay.

## Mac app

Open `Age-of-Collapse-Balance-Lab-macOS.dmg`, drag **Age of Collapse Balance Lab**
to Applications, and launch it there. The universal app targets macOS 13 or
later and includes Python for Apple Silicon and Intel. It runs offline in a
native window. Saved studies live in
`~/Library/Application Support/Age of Collapse Balance Lab/Studies`.

To rebuild from the repository root, run `sh tools/package_balance_lab_macos.sh`.
The builder uses the macOS command-line tools and fetches checksum-pinned
CPython runtimes and license notices. It writes the disk image in
`builds/balance-lab-macos` by default. Pass a new output directory for another
build. This creates an ad-hoc signed test build. Sharing with a standard
Gatekeeper first launch requires Developer ID signing and Apple notarization.

## Dice expedition

In **Map**, select **Place farm** and paint as many underground farms as
you like. Use **Clear tile** for one farm or **Clear all farms** for a
farm-free layout. Click a wall segment or use the gateway column menus to
relocate the three crossings. Move the Surface crossing to relocate the
Surface Exit. Regular mines remain available on farm-free maps, and
generated map families preserve the number of farms in each zone.

When a map has multiple farms, the map table lists each one. Farm relocation
searches move the first farm in the selected zone, in text-map order. The
optional deep cache remains one payout at the first Zone 3 farm.

The viewer opens on the current five-seat no-cache **Dice** preset. Earlier
rulesets are available in Settings, and the archived experiments are under
Rules. The current preset starts with 4 Energy and adds 2 per later
round, move two steps per Energy, and carry up to 10. Set Starting Energy and
Energy gained per round separately under Energy. Zones are open from
round 1. You draw from the three shared decks by mining at marked sites.
A regular mine costs 1 Energy for one card. A farm costs 2 Energy for two
cards. Clearing an adjacent rock uses the regular mine cost. Treasure values, each zone's HP
range and attack, gear prices, and the defeat pushback are editable.

Fights resolve one d6 exchange at a time. Swords add damage, and shields
absorb Energy damage from surviving monsters. Losing a fight drops the
entire carried hand. Walk onto the Surface Exit to bank automatically
and continue playing. You can spend carried or banked Treasure cards at
shops. Surface shops sell starting gear and underground Blacksmiths
upgrade gear up to their zone level. The dice replay shows the rolls,
results, bounties, and banking. To reproduce the balance study run
`python3 tune_dice.py` from this directory.

Run `python3 tune_treasure.py --train-games 20 --holdout-games 150` to
compare Treasure ranges with the current deck counts. The search tunes
each depth's banking threshold, return buffer, gear spending, and use of
alternate mines against the other routes. The holdout reports score,
Surface finish, mining at the intended depth, and fractional wins per
seat. This is a search over five policies per depth with one
best-response sweep. Results print as JSON lines.
Run `python3 tune_treasure.py --confirm --holdout-games 180` to
compare the two finalists on fresh seeds, both with a lone Zone 1 farmer
and with the number of shallow seats rotating.

Run `python3 tune_shop.py --games 100` for the first-purchase study.
It rotates one tested seat against four no-purchase routes and compares
early trips to buy gear with purchases during normal banking. The
output includes per-purchase cost and savings, qualifying scores, win
shares, and paired score differences. Pass `--starter-prices 1 1 2` to
test alternative Shield, Sword, and Boots prices.
The no-cache preset uses one-gold Sword and Shield, two-gold Boots,
starter Sword and Shield at underground shops, and one extra point of
damage with an equipped Sword. Purchases deduct exact value from carried
Treasure first and banked Treasure second. One card can cover the price
and keeps its leftover value. Run `python3 tune_shop.py --modes field opening --recommended-modes`
for the policies used to check that preset.
The preset charges 1 Energy to move one or two squares, or up to four
with Boots. Speed Potion doubles the next Move's range at the same cost.

## Strategy balance

Open **Strategy balance**, select **Load current test preset**, and run
the matched study. You can change the loaded map, rules, or seed before
running. Each lineup compares fixed routes with an adaptive policy while
preserving one strict Zone 1 farmer. Route labels identify the same
seats in both conditions. Adaptive choices use the visible standings,
available mines, current equipment, and the Energy budget for returning.

The dashboard reports average qualifying gold, split win chance per
seat, 90th-percentile scores, average winning scores, and approximate
95% ranges grouped by game. The funnel measures entry, mining, a later
deposit, and qualification on Surface. The gear audit tests one
purchase policy at a time against no purchase on the same seeds and
reports gold paid, Energy saved, and score change. Export study JSON
to keep the map, settings, seed, and results together.

For the same study outside the viewer, run
`python3 balance_study.py --games 100` from this directory.

To compare farm placement and opening Energy against the previous map
and two-Energy opening, run `python3 tune_farm_routes.py --both-lineups`.
It reports actual mining depth and farm draws alongside fixed-route
scores and the rate of banking after mining.

## Settings search

Choose from 20 presets to compare Energy, farm and mine placement, treasure
values, 50-card deck composition, combat, equipment, boss pressure, round limits,
and table size. Each search runs its variants and the current setup on matched
seeds with both fixed and adaptive policies and two mixes of shallow competition.
The current setup and up to three finalists are then run on fresh seeds. Review
score and win share by route, actual mining depth, and the rate of mining and
then banking before using **Apply & run** to load a finalist's rules and map.
The detail panel includes deck draw and depletion rates, combat, purchases, and
estimated tabletop time. The small default samples are for screening. Increase
fresh games per matchup before drawing conclusions about close candidates.

Presets use Dice rules and accept 3–8 seats and at most 30 rounds. The
table-size preset tests 3–6 seats. The four experimental settings default to
unlimited shared farm use, four-square Boots on 1-Energy movement, one Energy
block per Shield level, and a three-Energy entrance Tonic. With a positive
shared farm limit, the farm counts activations by all seats and resets each
round. Each seat retains its personal one-activation limit. For a single
metric and a custom grid of settings, open **Manual target search**.
Choose a target to get close to, meet or exceed, or stay under. For example,
target **at most 45** cards at the Zone 3 draw percentile to look for a
five-card reserve, or target **at least 30%** of seats mining in Zone 3,
depositing later, and qualifying on Surface. The latter counts positive
deposits after mining and does not trace their gold to a specific card.
The search skips illegal combinations such as deck counts over 50. It checks
the baseline and finalists on the same fresh seeds, using complete matches
for shared decks. Timing targets show no estimate if no player reached the
event.

### Large Study

Open **Settings search → Large Study**. The starter template crosses opening
Energy, refill, Zone 1 farm distance and farm activation cost. Add up to 12
axes using comma-separated whole numbers or `min:max:step`. A farm distance
axis uses changes in walking steps from the selected map's farm. Load saved
map JSON files or generate connected maps with the same per-zone site counts.
Preview shows the candidate workload, invalid choices and actual farm distances.

An exact Treasure axis takes a JSON list such as `[{"2":6,"4":6}, {"3":12}, null]`.
The first two profiles each contain 12 Treasure cards with the same mean gold
value. `null` uses the min/max range. The zone's Monster and fixed Item counts
leave the rest of its 50 cards available for Treasure and Nothing. Applying a
profile keeps exact values through simulation, settings export and replay.
In Rules, **Use range** clears the applied profile for an individual zone.

A rotation tests each starting seat with a matched seed. The four matchups
cover fixed lone-farmer and shallow-heavy play, plus adaptive mixed and
deep-heavy play. Refinement retunes one route at a time from a finite menu of
policies while preserving the strict Zone 1 farmer. Validation uses a separate
seed block with both policy profiles. The three result views prioritize
different balance goals. Use the screening heatmap to inspect interactions
and the fresh-seed comparison to evaluate a specific setup. “Mined then banked”
means a seat made a later deposit after mining that zone. It does not attribute
individual banked gold cards to a zone.

Select **Pause study** to keep completed seat rotations. **Saved study** can
resume the work after a browser or server restart. **Study JSON** includes
the candidates and stage summaries. **Match CSV** includes each completed
match's seed, lineup, policy, settings and results. Checkpoints live in the
ignored `.large_studies` directory beside the server.

## Shared zone decks

Both shared-deck modes have one shuffled 50-card
deck in each zone. Players use Move and Mine, with immediate Combat on a
Monster draw. Decks do not refill. The **Zone decks** settings expose the
mode switch and starting upgrade and item values. A new shared-deck setup
uses ordinary terrain movement costs by default. Adjust the darkness and
rough-ground multipliers to increase travel costs.

Dice mode starts with these mixes and Treasure ranges. Edit Monster and
Treasure counts in **Dice rules**. Nothing fills the unused slots after
the fixed Item cards.

| Zone | Monster | Treasure | Nothing | Items | Treasure value |
|---|---:|---:|---:|---:|---:|
| 1 | 10 | 12 | 18 | 10 | 1–4 |
| 2 | 13 | 24 | 3 | 10 | 4–8 |
| 3 | 17 | 28 | 0 | 5 | 6–12 |

The earlier automatic-combat shared-deck mode uses its original mix:

| Zone | Monster | Treasure | Nothing | Items |
|---|---:|---:|---:|---:|
| 1 | 10 | 15 | 15 | 10 |
| 2 | 15 | 20 | 5 | 10 |
| 3 | 20 | 25 | 0 | 5 |

The initial item copies are:

- **Zone 1** — Pickaxe ×2, Bow, Speed Potion, Energy Potion ×2, Grenade,
  Shovel ×2 and Coupon.
- **Zone 2** — Pickaxe, Bow, Speed Potion, Energy Potion, Energy Canister,
  Grenade, Shovel, Teleport Potion, Thief’s Tools and Coupon.
- **Zone 3** — Energy Potion, Energy Canister, Grenade, Teleport Potion
  and Thief’s Tools.

Shop upgrades and Boots cost Treasure cards. Coupon reduces the number
spent by one. The sword starts at level 1 and the shield starts at level
0. Both can reach level 3. The replay shows monster fights, item use and
remaining cards. See [agent play](AGENT_PLAY.md) for the full command syntax.
Choose Independent draws for the probability controls and Action audit.
Stop the server with Ctrl+C. Use `--port 8766` for another port. Python 3.9+
standard library only; no Tk, package installation, CDN or hosted service.

## Workflow

Change numbers/sliders, then **Run simulations**. The action stays visible while
settings scroll. **Overview** includes score, extraction, zone reach, energy,
equipment ownership, potion usage, and area-collapse results, plus actual metric values.
**Explore a run** replays the first 40 players, with all actions and calculations.
Results CSV contains every player; turn-log CSV contains the selected player.
Save/load JSON preserves inputs. Version 1 settings import removes the obsolete
fixed step cap and adds the new equipment, farming and boss defaults.

**Settings search** accepts a target and absolute tolerance (percentage points
for rates). Choose 1–4 editable rules and integer min/max/step ranges. The
optimizer tests the whole grid if it fits, otherwise a seeded unique sample.
Unselected rules stay fixed. The top five candidates receive a fresh-seed
check, then are ranked by target distance. **Apply & run** restores that search's
settings snapshot with the chosen changes and runs the full experiment.
An unreachable target reports the closest tested result. This is bounded search
against point estimates, not a guarantee or proof of a global optimum.

**Action audit** compares decisions on the selected map and settings. It samples
one occurrence per player in each action category and replays that decision
with the same starting random streams and boss rolls. It reports the change in
final banked treasure and escape rate, how often players choose the action, and
an approximate 95% loot interval that accounts for shared boss rolls. The
comparison ends the turn for a skipped farm or exploration step, retreats
instead of entering a deeper zone, defers a purchase until the next turn, or
holds a potion at that decision. Check the alternative beside each result.
Review flags require at least 25% player coverage, 40 paired players across
12 games, a positive interval, the configured minimum gain, and an escape
drop of at most two percentage points. Estimates apply to sampled decisions
under the current policy.

## Energy and snake route

Open **Map** to edit the 6×10 board. The map is drawn with Surface at
the bottom. Click with a brush or type ten rows of six characters into the
editor, beginning with the Surface row. Use `.` for floor, `#` for rocks,
`F` for the two-card farm, `M` for a regular mine and `S` for shops. Gate dropdowns select the sole
crossing column at each boundary. All open tiles must connect to Surface.
Original snake, Compact spine and Rock switchbacks are starting layouts.

The table shows shortest walking distances. Click **Run this map** for a
seeded experiment or **Run and watch** for a step-by-step replay with `@`
representing the player. The comparison uses the two most recent runs.
Keep the seed and rule settings fixed to isolate layout changes. The shop
detour checkbox lets every strategy visit its nearest in-zone vendor when
it can afford its next item. Saved settings include the map.

**Compare route decisions** runs matched conditions with the current seed
and rules. Farm trials move only the chosen Zone 1 or 2 farm and use the
shortest route via the farm minus the direct gate-to-gate route. The nearest
valid farm tile is tested for each of 2, 4 and 6 extra steps. A distance that
cannot fit the layout is reported as unavailable. Use **Load map** to keep
one of the trial layouts. The farm detour limit under Farming lets players
skip a farm whose extra walking steps exceed their limit.

The retreat trial compares the configured retreat turn with an energy-aware
policy. After visiting the cave, the policy estimates future refills for
each step on the shortest return path, using current energy and permanent
gear. It commits to retreat at the configured slack threshold. The estimate
does not count consumables or forecast collapse.

**Is Zone 3 worth it?** Compares policies that stop at Zone 2 or attempt
Zone 3, with and without the cache. First reaching the Zone 3 farm awards
six carried treasure by default. The cache is collected once per player
and follows normal spending, loss and extraction rules. Repeated farming
continues to draw its usual cards. Set the cache value under Rewards, or
use zero to disable it. The study reports reach, claim rate, escape and
banked loot, including zero for players who fail to extract. These policies
do not change their depth preference in response to the payout.

Equipment trials toggle a single item and report direct energy saved on
actual walking steps while holding the remaining gear and potion use fixed.
This direct estimate differs from the total walking energy gap between the
two simulated policies, since item availability can change routes and purchases.
Check the latest-run diagnostics for gate entry counts and timing, farm and
shop activity, energy waits, and the final zone of players who did not extract.

**Find layouts near 75% escape** screens different gate, farm, shop, and
rock configurations. Each has one opening per boundary. The target is for
escape-first players using energy-aware retreat with the configured slack.
Late players use the fixed retreat turn or the penultimate turn, whichever
is later. The search favors layouts close to the target where escape-first
players escape more often. The current board and the five strongest
candidates run again on a fresh seed. The comparison shows boss fatalities
and banked treasure per player, including zeroes.
**Load tested 75% setup** loads the selected switchback layout, a turn-11
monster that advances on 3+, and one turn of return slack. It preserves the
seed, game count and player count. Compare retreat policies on seed 20291190
with 1,000 four-player games to reproduce the confirmation run.

The board remains 6×10: one Surface row (6 spaces), then three 18-space zones.
Start (0,0), with coordinates starting at zero. Crossings between Surface/Zone 1,
Zones 1/2, and Zones 2/3 are restricted to columns 0, 5 and 0 respectively.
All other edges across these boundaries are blocked in both directions.

There is no walking step limit. Regenerate Energy once per turn, carry to the
cap, and spend available Energy on movement, farming and combat. Exact payment
to zero is legal. Unaffordable movement or farming waits without spending or
consuming randomness. The AI may rest after its farm quota. Zone-access turn
thresholds allow travel but never change position directly.

Farms at (0,3), (5,6), (5,9) sit opposite the next gate or deep entrance. The
deepest farm requires **24 adjacent tile steps** to walk back to Surface.
Retreat uses those same gates; it cannot walk straight through boundary walls.

## Equipment shops

Shops marked **S** trade carried loot for permanent equipment. Players can
carry three items by default. Prices, purchase switches, and available slots
are editable. A slot stays occupied for the run.

| Equipment | Loot price | Effect |
|---|---:|---|
| Boots | 3 | Halve tile movement energy |
| Flashlight | 3 | Remove the darkness surcharge in Zones 2 and 3 |
| Climbing Kit | 5 | Remove the rough-ground surcharge in Zone 3 |
| Mining Pick | 5 | Reduce farm activation cost by 1, to a minimum of 1 |
| Padded Pack | 4 | Prevent up to 2 loot loss per monster knockdown |
| Cave Blade | 6 | Reduce combat cost by up to 2 energy per Monster card |
| Prospector Charm | 6 | Award 1 extra loot per Treasure card |
| Spare Battery | 8 | Regenerate 1 extra energy starting the turn after purchase, within the cap |
| Trail Map | 4 | Save 0.5 energy per retreat step, to a minimum of 0.25 |
| Safety Harness | 5 | Reduce monster pushback by one zone and reduce boss ejection losses by up to 2 loot and 1 energy |

Darkness and rough-ground costs stack before the Boots and Trail Map discounts.
Terrain uses the harder of the two tiles, including on retreat.

Choose **Balanced**, **Farm and profit**, **Deep expedition**, or **Safe return**
under Shopping priority. These set purchase order. The AI saves for the next
enabled item, skips Flashlight and Climbing Kit when its maximum zone makes
them unnecessary, and stops shopping on retreat. Farm and profit takes an
in-zone shop detour when it can afford its next item. Set the deepest zone,
farm quota and retreat turn independently. **Compare the last two runs** shows
loot, voluntary escape, depth, spend and knockdowns side by side.

**Mixed, price-aware shoppers** draw one of the four shopping preferences
per player and apply seeded variation to how much they value each item.
They rank items by value divided by price plus three and save up for the
top eligible item. This lets a price change affect what enters a loadout.
The same seed gives the same preferences for each player across price tests.

The Equipment balance experiment buttons compare the original and tuned
prices with that shopper mix, all ten items enabled and three slots.
The **Used** column counts players whose item changed a cost, reward,
energy gain, ejection loss or knockdown position at least once. A purchase
alone only counts in **Owned**. Run both price sets with identical game
settings to see the usage spread alongside score and voluntary escape.

Reproduce the price search from this directory with
`python3 tune_equipment.py --players 280`. The search tries integer prices in
1–14, penalizes low average item use, score loss, and escape loss, and checks
the best candidate on a separate seed with 4,000 players. It estimates how
this simulated shopper mix responds to prices.

## Single-use potions

Each encounter card independently has a 12% chance of finding a bonus potion
after it resolves. Both cards in a farm activation roll for a find. Each of the
five types is equally likely. Finding a potion does not replace the encounter,
and it can only be used on a later action. Potions occupy no permanent gear
slot. Their discovery stream is seeded separately from encounters and the boss.

| Potion | AI consumption trigger and effect |
|---|---|
| Energy Tonic | When the next action is unaffordable, restore up to 3 energy within the cap |
| Haste Potion | Halve one movement cost when it saves energy |
| Glow Potion | Remove the darkness surcharge for one step without a Flashlight |
| Ward Potion | Reduce an otherwise unaffordable combat batch by up to 4 energy |
| Fortune Potion | Award 3 extra loot on the next batch containing Treasure |

Toggle automatic use to measure the effect of finding the same supplies without
spending them. Movement prefers using at most one potion and combines Glow and
Haste if needed to afford the step. Replay shows the finds, uses and inventory.
The Overview reports counts by potion type.

Each player finds one guaranteed Energy Tonic on their first discovery at the
Zone 3 entrance, after the encounter resolves. It appears in the usual potion
inventory and can restore up to 3 Energy on a later action. The reward follows
the configured gate column and works independently of random potion finds.
Replay labels the gate supply and records its collection. Toggle **Zone 3
entrance Energy Tonic** under Potions to compare runs with and without it.
Imported older settings without this switch load with the reward disabled.

## Mining and encounter odds

Each player can activate each site once per turn. The special farm (`F`) draws
two cards in a batch. A regular mine (`M`) draws one. Both cost 2 Energy by
default, and the Mining Pick reduces either cost. A player can mine several
sites in one turn by walking and paying at each. Arrival still draws the
ordinary first-entry card. Saved layouts without mines keep their exact tiles.

Standard, mining-focused, and gear-focused policies use the activation quota
before advancing where possible. Deep-delving heads onward when the gate
opens. Set the quota to zero to skip paid draws. The same editable odds apply
to discovery and mining. Nothing is the remainder after the other three
outcomes. Overview shows the observed card counts and how many Nothing draws
also failed the separate potion roll.

The confirmed presets load the Tested snake layout, card odds and gear
settings. Strategy parity favors similar banked scores across policies.
Deep rewards and gear variety favors the deep payout and more even item
usage. Choose a route policy before loading. The table averages both study
maps and both holdout seeds. The linked JSON has per-map and per-seed trials,
plus mining counterfactuals and individual item removal results for Strategy parity.
Reproduce the search from this folder with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tune_cave.py > /tmp/aoc-initial-balance.json
PYTHONDONTWRITEBYTECODE=1 python3 tune_cave.py --refine /tmp/aoc-initial-balance.json --screening 400 > /tmp/aoc-refined-balance.json
```

Combat retains average damage: rounds = ceil(HP / average attack roll).
Energy cost = rounds × base outward cost + (rounds − 1) × monster attack.
At the defaults a Zone 3 monster costs 9 Energy, or 7 with a Cave Blade.
A deficit causes knockdown: lose configured loot and relocate to a safe gateway
the configured number of zones back. Knockdown ends movement for that turn.
It never banks loot by itself.

## Boss and area collapse

Default arrival is turn **12**, in Zone **3**. At the end of each round it rolls
one shared d6 for that game. On **4+**, its entire current zone closes permanently
and it advances to the next shallower zone (3→2→1). A lower roll holds position.
It cannot collapse more than one zone in a round. There are no rolls after all
three zones have closed. Arrival, threshold and enable switch are editable.

When Zone 3 or 2 closes, players there are pushed toward the Surface and lose
up to 2 treasure and 2 energy by default. On the final advance, the monster
seals the entrance and kills everyone still underground. Carried treasure is
lost. A player who walks out before the end-of-round roll is safe. Collapsed
tiles reject future entry.

Final game standings rank survivors by banked treasure, with ties sharing
first. A game with no escapees has no winner.

The boss schedule is shared by players in a game and uses a separate RNG stream
(`seed + 700000003 + game_index × 15485863`). Encounter streams are independent
per player (`seed + player_index × 104729`). Purchases or encounter consumption
cannot change the boss's dice. Settings and seed reproduce every result.

## Metrics and limits

Escape requires reaching the Surface and extracting. Score averages include
zero scores and deduct shop
spend and penalties. Unbanked loot is mean carried loot still underground at the
deadline; shop spend, boss losses and knockdown losses are separate. Zone reach
counts actual entry even when immediately knocked back. Collapse graph counts
games; equipment ownership and other rates count players.

Energy means use the final action each turn among active players. Extracted
players drop out in following turns. With the boss enabled, uncertainty uses
game-cluster normal approximations, widening escape bounds at least to the
independent-player Wilson interval. A single game has no score interval and a
0–100% escape bound. Disabled boss uses independent-player Wilson escape bounds
and normal score intervals. Small or skewed samples need caution. Candidate and
confirmation sizes count players; the shared boss introduces correlation within
games, so more games give stronger evidence than more players in one game.

The localhost server permits one experiment at a time, supports cancellation,
keeps at most eight jobs in memory, and serves only its web assets. Runs are
limited to 50,000 players and a work estimate of four million units, based on
turns, energy capacity and farming quota. Search is limited to 150 candidates,
1,000 player trials per candidate and 5,000 confirmation players per finalist.

The rules change this standalone balance tool, not the Godot expedition. There
is no PvP, shared encounter depletion, finite decks or character perks. Numerical
prices, penalties and AI choices are editable balance proposals.

## Agent matches

Separate agents can play the balance model through a persistent JSON CLI with
seat-specific observations, legal commands, revision checks, shared rounds,
deterministic save continuation, and survivor standings. See the
[agent play instructions](AGENT_PLAY.md) for setup, coordination and a player
prompt. Existing automated web experiments are unchanged.

## Checks

```sh
python3 -m unittest discover -s . -v
node --check static/app.js
```

Behavioral tests cover Energy spending, two-for-one Boots, multipliers in both
directions, repeatable two-card farms, gateway topology, atomic rejections,
shop stock and affordability, shared boss dice, permanent collapse, evacuation,
round timing, loot/Energy reconciliation, deterministic replay and target search.
HTTP tests require permission to bind a temporary loopback port.
