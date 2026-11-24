"""Calibrate early boss victory rates against matched five-seat bot games."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

from engine import board_from, settings_from, shared_game


FOLDER = Path(__file__).with_name('playtests')
TRAIN_SEED = 20261124
HOLDOUT_SEED = 20271124


def measure(preset, seed, games, changes=None):
    settings = settings_from({**preset['settings'], **(changes or {}), 'seed': seed})
    board = board_from(preset['board'])
    counts = Counter()
    loadouts = {}
    for index in range(games):
        _, players = shared_game(settings, board, index, settings.players, None)
        for player in players:
            counts['surface'] += player.get('surface', player['escaped'])
            counts['knockdowns'] += player['knockdowns']
            for row in player['rows']:
                action = row['action']
                if action.startswith('Buy '):
                    counts[action] += 1
                if action == 'Challenge':
                    counts['duels'] += 1
                    counts['challenger_wins'] += row['duel']['winner'] == row['duel']['actor']
                if row.get('boss_attempt'):
                    counts['attempts'] += 1
                    counts['boss_kills'] += row['boss_defeated']
                    fight = row['combat_events'][0]
                    kit = (row['sword'], row['shield'], bool(fight['exchanges'][0]['grenade']))
                    loadout = loadouts.setdefault(str(kit), Counter())
                    loadout['attempts'] += 1
                    loadout['kills'] += row['boss_defeated']
    return dict(games=games, seats=games*settings.players, counts=counts,
                boss_kill_rate=counts['boss_kills']/games, loadouts=loadouts)


def trial(entry):
    preset, hp, threshold = entry
    changes = dict(boss_hp=hp, boss_challenge_pct=threshold)
    return changes, measure(preset, TRAIN_SEED, 400, changes)


def main():
    preset = json.loads((FOLDER/'rolled_combat_playtest.json').read_text())
    baseline = json.loads((FOLDER/'combat_playtest.json').read_text())
    candidates = product((preset,), (24, 28, 32), (45, 55, 65))
    with ProcessPoolExecutor(max_workers=4) as executor:
        trials = list(executor.map(trial, candidates))
        for settings, results in trials:
            print(json.dumps(dict(settings=settings, **results)), flush=True)
        selected, _ = min(trials, key=lambda pair: (
            abs(pair[1]['boss_kill_rate']-.065), abs(pair[0]['boss_hp']-28), -pair[0]['boss_challenge_pct']))
        comparison = executor.submit(measure, baseline, HOLDOUT_SEED, 1000)
        holdout = executor.submit(measure, preset, HOLDOUT_SEED, 1000, selected)
        print(json.dumps(dict(holdout=holdout.result(), baseline=comparison.result(), selected=selected)), flush=True)


if __name__ == '__main__':
    main()
