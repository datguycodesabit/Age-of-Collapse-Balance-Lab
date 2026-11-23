import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from agent_match import AgentMatch
from model import path_between


def act(match, kind, **payload):
    return match.submit(dict(actor=match.active, revision=match.revision,
                             action=dict(kind=kind, **payload)))


class AgentMatchTests(unittest.TestCase):
    def match(self, **settings):
        return AgentMatch(dict(players=2, p_treasure=100, p_monster=0,
                               p_enhance=0, potion_chance=0, **settings))

    def test_invalid_commands_preserve_state_and_all_random_streams(self):
        match = self.match()
        saved = copy.deepcopy(match.__dict__)
        before = match.observation(0)
        for command in (None, {}, dict(actor=1, revision=0, action={'kind':'EndTurn'}),
                        dict(actor=0, revision=1, action={'kind':'EndTurn'}),
                        dict(actor=0, revision=0, action={'kind':'Buy','item':[]}),
                        dict(actor=0, revision=0, action={'kind':'Delve','destination':[0,True]}),
                        dict(actor=0, revision=0, action={'kind':'Delve','destination':[0,1.0]}),
                        dict(actor=0, revision=0, action={'kind':'Delve','destination':[5,9]}),
                        dict(actor=0, revision=0, action={'kind':'Extract'})):
            self.assertFalse(match.submit(command)['accepted'])
            self.assertEqual(match.observation(0), before)
            self.assertEqual(match.serialize()['commands'], [])
        for i in range(2):
            self.assertEqual(match.rngs[i].getstate(), saved['rngs'][i].getstate())
            self.assertEqual(match.players[i].potion_rng.getstate(), saved['players'][i].potion_rng.getstate())

    def test_mining_limit_resets_and_purchase_spends_scoreable_loot(self):
        match = self.match()
        for y in (1,2,3):
            self.assertTrue(act(match, 'Delve', destination=[0,y])['accepted'])
        self.assertTrue(act(match, 'Farm')['accepted'])
        self.assertFalse(act(match, 'Farm')['accepted'])
        act(match, 'EndTurn')
        act(match, 'EndTurn')
        self.assertTrue(act(match, 'Farm')['accepted'])
        for y in (2,1,0):
            self.assertTrue(act(match, 'Retreat', destination=[0,y])['accepted'])
        loot = match.players[0].loot
        self.assertTrue(act(match, 'Buy', item='Boots')['accepted'])
        self.assertEqual(match.players[0].loot, loot-match.settings.boots_price)
        self.assertFalse(act(match, 'Buy', item='Boots')['accepted'])
        self.assertTrue(act(match, 'Extract')['accepted'])
        self.assertEqual(match.players[0].bank, loot-match.settings.boots_price)

    def test_zone_opening_and_knockdown_end_turn(self):
        match = AgentMatch(dict(players=2, p_treasure=0, p_monster=100,
                                p_enhance=0, potion_chance=0, hp1=100))
        self.assertTrue(act(match, 'Delve', destination=[0,1])['accepted'])
        self.assertEqual(match.active, 1)
        self.assertEqual(match.players[0].position, (0,0))
        self.assertEqual(match.players[0].energy, 0)
        match = self.match(gain=100, cap=100)
        for destination in ([0,1],[0,2],[0,3],[1,3],[2,3],[3,3],[4,3],[5,3]):
            self.assertTrue(act(match, 'Delve', destination=destination)['accepted'])
        self.assertFalse(act(match, 'Delve', destination=[5,4])['accepted'])
        for _ in range(3):
            act(match, 'EndTurn')
            act(match, 'EndTurn')
        self.assertTrue(act(match, 'Delve', destination=[5,4])['accepted'])

    def test_shared_round_refill_and_duplicate_revision(self):
        match = self.match()
        command = dict(actor=0, revision=0, action={'kind':'Delve','destination':[0,1]})
        self.assertTrue(match.submit(command)['accepted'])
        self.assertEqual(match.players[0].energy, 5)
        self.assertFalse(match.submit(command)['accepted'])
        act(match, 'EndTurn')
        self.assertEqual((match.active, match.round, match.players[0].energy), (1,1,5))
        act(match, 'EndTurn')
        self.assertEqual((match.active, match.round, match.players[0].energy), (0,2,10))

    def test_extraction_skip_finished_players_and_shared_tie(self):
        match = self.match()
        for actor in (0,1):
            self.assertEqual(match.active, actor)
            self.assertTrue(act(match, 'Delve', destination=[0,1])['accepted'])
            self.assertTrue(act(match, 'Retreat', destination=[0,0])['accepted'])
            self.assertTrue(act(match, 'Extract')['accepted'])
        view = match.observation(0)
        self.assertTrue(view['complete'])
        self.assertEqual(view['winners'], [0,1])
        self.assertEqual([p['bank'] for p in view['standings']], [2,2])
        self.assertEqual(view['legal_actions'], [])
        self.assertFalse(act(match, 'EndTurn')['accepted'])

    def test_boss_only_rolls_after_every_seat_and_can_leave_no_winner(self):
        match = self.match(boss_start=1, boss_threshold=1)
        for round_number in (1,2,3):
            act(match, 'EndTurn')
            self.assertEqual(len(match.boss_events), round_number-1)
            act(match, 'EndTurn')
            self.assertEqual(len(match.boss_events), round_number)
        self.assertEqual(match.closed, (1,2,3))
        self.assertNotIn({'kind':'Delve','destination':[0,1]}, match.legal_actions(0))
        while not match.complete:
            act(match, 'EndTurn')
        self.assertEqual(match.observation(0)['winners'], [])

    def test_boss_kills_underground_but_extracted_player_wins(self):
        match = self.match(boss_start=1, boss_threshold=1)
        act(match, 'Delve', destination=[0,1])
        act(match, 'Retreat', destination=[0,0])
        act(match, 'Extract')
        act(match, 'Delve', destination=[0,1])
        while not match.complete:
            act(match, 'EndTurn')
        self.assertTrue(match.players[1].killed)
        self.assertEqual(match.players[1].loot, 0)
        self.assertEqual(match.observation(0)['winners'], [0])

    def test_observations_hide_future_and_other_hands_and_are_copies(self):
        match = self.match()
        act(match, 'Delve', destination=[0,1])
        view = match.observation(1)
        self.assertNotIn('seed', view['settings'])
        self.assertNotIn('loot', view['players'][0])
        self.assertEqual(view['your_log'], [])
        self.assertEqual(view['boss_events'], [])
        self.assertEqual(view['legal_actions'], [])
        view['players'][0]['equipment'].append('Boots')
        self.assertNotIn('Boots', match.players[0].equipment)

    def test_save_continuation_replays_full_random_match(self):
        match = AgentMatch({'players':4})
        chooser = random.Random(45)
        restored = None
        for step in range(3000):
            actor = match.active
            if actor is None:
                break
            actions = match.legal_actions(actor)
            action = chooser.choice(actions)
            command = dict(actor=actor, revision=match.revision, action=action)
            result = match.submit(command)
            if restored:
                self.assertEqual(result, restored.submit(command))
                self.assertEqual(match.observation(actor), restored.observation(actor))
            if step == 20:
                restored = AgentMatch.restore(json.loads(json.dumps(match.serialize())))
        self.assertTrue(match.complete)
        self.assertIsNotNone(restored)
        self.assertEqual(match.serialize(), restored.serialize())
        damaged = match.serialize()
        damaged['commands'][0]['revision'] = -1
        with self.assertRaises(ValueError):
            AgentMatch.restore(damaged)

    def test_cli_separate_processes_and_atomic_stale_submission(self):
        cli = Path(__file__).with_name('agent_cli.py')
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)/'match.json'
            def run(operation, *args):
                result = subprocess.run([sys.executable,str(cli),operation,'--state',str(state),*args],
                                        capture_output=True, text=True, timeout=10)
                return result.returncode, json.loads(result.stdout)
            code, first = run('create')
            self.assertEqual(code, 0)
            command = json.dumps(dict(actor=0,revision=0,action={'kind':'EndTurn'}))
            code, result = run('act','--command',command,'--actor','1')
            self.assertEqual(code, 0)
            self.assertEqual(result['observation']['active_actor'], 1)
            saved = state.read_bytes()
            self.assertEqual(run('act','--command',command)[0], 2)
            self.assertEqual(state.read_bytes(), saved)
            self.assertEqual(run('create')[0], 1)
            self.assertEqual(state.read_bytes(), saved)
            self.assertEqual(run('observe','--actor','1')[1]['observation'], result['observation'])
            command = json.dumps(dict(actor=1,revision=1,action={'kind':'EndTurn'}))
            processes = [subprocess.Popen([sys.executable,str(cli),'act','--state',str(state),
                                           '--command',command], stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True) for _ in range(2)]
            responses = [json.loads(process.communicate(timeout=10)[0]) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0,2])
            self.assertEqual(sum(response['result']['accepted'] for response in responses), 1)
            self.assertEqual(run('observe')[1]['observation']['revision'], 2)

    def test_gate_tonic_replays_and_legacy_journals_keep_their_rules(self):
        for enabled,attack in ((1,3),(0,5)):
            match = self.match(zone2_start=1,zone3_start=1,gain=40,cap=40,
                               atk3=attack,deep_entry_tonic=enabled)
            route = path_between(match.board.start,match.board.entrance(3),board=match.board)
            for tile in route[1:]:
                result = act(match,'Delve',destination=list(tile))
                self.assertTrue(result['accepted'])
            self.assertEqual(result['event']['gate_tonic'],bool(enabled))
            if enabled:
                self.assertIn({'kind':'Tonic'},match.observation(0)['legal_actions'])
                self.assertTrue(act(match,'Tonic')['accepted'])
            journal = json.loads(json.dumps(match.serialize()))
            if not enabled:
                del journal['settings']['deep_entry_tonic']
            restored = AgentMatch.restore(journal)
            self.assertEqual(restored.observation(0),match.observation(0))


if __name__ == '__main__':
    unittest.main()
