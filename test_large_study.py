"""Large Study design, exact decks, and durable stage execution."""
import csv
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import large_study
from agent_match import AgentMatch
from dice_rules import decks
from engine import board_from, settings_from
from model import zone_at
from study_design import assignment, distance, generated_family, make_design
from tune_turn_length import PRESET


class LargeStudyTests(unittest.TestCase):
    def setUp(self):
        self.preset=json.loads(PRESET.read_text())
        self.settings=settings_from(self.preset['settings'])
        self.board=board_from(self.preset['board'])

    def test_starter_and_generated_maps_are_legal_deterministic_and_distinct(self):
        design=make_design(self.settings,self.board,{})
        self.assertEqual(design,make_design(self.settings,self.board,{}))
        self.assertGreater(len(design['candidates']),50)
        self.assertGreater(design['rejected'],0)
        self.assertEqual(design['candidates'][0]['board'],self.preset['board'])
        self.assertEqual(len(design['candidates']),
                         len({json.dumps([c['settings'],c['board']],sort_keys=True)
                              for c in design['candidates']}))
        bounds=[(2,5),(8,13),(18,26)]
        maps=generated_family(self.board,self.settings.seed,3,bounds)
        self.assertEqual(maps,generated_family(self.board,self.settings.seed,3,bounds))
        self.assertEqual(len(maps),3)
        for layout in maps:
            for tile,(lo,hi) in zip(layout.farms,bounds):
                self.assertLessEqual(lo,distance(layout,tile))
                self.assertLessEqual(distance(layout,tile),hi)
            for field in ('mines','shops','rocks'):
                self.assertEqual(Counter(map(zone_at,getattr(layout,field))),
                                 Counter(map(zone_at,getattr(self.board,field))))

    def test_exact_cards_are_seeded_and_replay_while_old_ranges_still_work(self):
        base=self.preset['settings']
        profile={'1':{'2':6,'4':6}}
        s=settings_from(dict(base,treasure_profiles=profile))
        pile=decks(s)[1]
        self.assertEqual(len(pile),50)
        self.assertEqual(Counter(v for kind,_,v in pile if kind=='Treasure'),{2:6,4:6})
        self.assertEqual(decks(s)[2],decks(self.settings)[2])
        self.assertEqual([card for card in pile if card[0]!='Treasure'],
                         [card for card in decks(self.settings)[1] if card[0]!='Treasure'])
        match=AgentMatch(dict(base,treasure_profiles=profile),self.preset['board'])
        self.assertTrue(match.submit(dict(actor=0,revision=0,action={'kind':'Move','destination':[0,2]}))['accepted'])
        replay=AgentMatch.restore(json.loads(json.dumps(match.serialize())))
        self.assertEqual(match.decks,replay.decks)
        self.assertEqual(match.observation(0),replay.observation(0))
        with self.assertRaisesRegex(ValueError,'must sum'):
            settings_from(dict(base,treasure_profiles={'1':{'2':11}}))

    def test_profile_and_treasure_count_axes_are_order_independent(self):
        exact=dict(key='treasure_profile1',values=[{'3':11}])
        count=dict(key='deck_treasures1',values=[11,12])
        for axes in ([exact,count],[count,exact]):
            definition=make_design(self.settings,self.board,{'axes':axes})
            self.assertEqual(definition['rejected'],1)
            self.assertEqual(definition['candidates'][1]['settings']['deck_treasures1'],11)
            self.assertEqual(definition['candidates'][1]['settings']['treasure_profiles'],{'1':{'3':11}})

    def test_every_mix_rotates_the_strict_farmer_through_every_seat(self):
        for seats in range(3,9):
            for scenario in range(4):
                ordered=[assignment(seats,scenario,g) for g in range(seats)]
                self.assertEqual({anchor for _,anchor in ordered},set(range(seats)))
                self.assertTrue(all(roles[anchor]==1 and set(roles)=={1,2,3}
                                    for roles,anchor in ordered))

    def test_pause_resume_matches_clean_run_and_exports_reproducible_results(self):
        settings=settings_from(dict(self.preset['settings'],players=3,turns=1,retreat_start=2))
        design=make_design(settings,self.board,dict(
            axes=[dict(key='start_energy',values=[5])],candidates=1,screen=1,refine=1,fresh=1))
        with tempfile.TemporaryDirectory() as folder, patch.object(large_study,'ROOT',Path(folder)):
            resumed=large_study.create(design)
            progress=[]
            with self.assertRaises(InterruptedError):
                large_study.run(resumed,progress.append,
                                lambda:bool(progress and progress[-1]['done']>=3))
            self.assertEqual(large_study.export_json(resumed)['status']['done'],3)
            result=large_study.run(resumed)
            clean=large_study.create(design)
            self.assertEqual(result,large_study.run(clean))
            self.assertEqual(list(large_study.export_csv(resumed)),list(large_study.export_csv(clean)))
            self.assertLessEqual(result['matches'],design['maximum_matches'])
            records=list(csv.DictReader(io.StringIO(''.join(large_study.export_csv(resumed)))))
            self.assertEqual(len(records),result['matches'])
            seeds={phase:{row['seed'] for row in records if row['stage']==phase}
                   for phase in ('screen','refine','fresh')}
            self.assertFalse(seeds['screen']&seeds['refine'] or seeds['screen']&seeds['fresh']
                             or seeds['refine']&seeds['fresh'])
            self.assertEqual(seeds['refine'],{r['seed'] for r in records if r['stage']=='retune'})
            delta=result['validation'][1]['retuned']['matchups'][0]['score_delta']
            self.assertTrue(all(row['games']==3 for row in delta))
            self.assertEqual(large_study.run(resumed),result)
