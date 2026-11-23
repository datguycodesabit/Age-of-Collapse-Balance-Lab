"""Resumable matched large studies. A checkpoint stores completed match batches."""
import csv
import fcntl
import io
import json
import os
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from balance_study import interval, play
from settings_presets import match_metrics, summarize
from study_design import MATCHUPS, assignment, canonical
from tune_treasure import POLICIES, Policy
from tune_shop import SEED_STRIDE

ROOT=Path(os.environ.get('AOC_STUDIES_DIR',Path(__file__).parent/'.large_studies'))
VERSION=1
MODULUS=2**53
BLOCK={'screen':0,'refine':3000017,'fresh':6000011}
POLICY_MENU={f'Banking {i}':policy for i,policy in enumerate(POLICIES,1)}
POLICY_MENU.update({
    'Regular mines first':Policy((5,13,19),3,False,True,'mine'),
    'Early Boots':Policy((7,17,24),2,True,True,'boots'),
    'Late deep push':Policy((5,14,22),2,True,True,'late'),
})


def path_for(identifier):
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):
        raise ValueError('Invalid study identifier.')
    return ROOT/f'{identifier}.sqlite3'


@contextmanager
def checkpoint(identifier):
    path=path_for(identifier)
    if not path.is_file():
        raise ValueError('Study checkpoint not found.')
    db=sqlite3.connect(path)
    try:
        version=db.execute('PRAGMA user_version').fetchone()[0]
        if version!=VERSION:
            raise ValueError('This study checkpoint belongs to a different simulator version.')
        yield db
    finally:
        db.close()


def create(design):
    identifier=uuid.uuid4().hex
    ROOT.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(path_for(identifier))
    try:
        with db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                PRAGMA user_version=1;
                CREATE TABLE metadata (name TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE batches (
                    key TEXT PRIMARY KEY, candidate INTEGER NOT NULL, phase TEXT NOT NULL,
                    matchup INTEGER NOT NULL, profile TEXT NOT NULL, payload TEXT NOT NULL
                );
            ''')
            put(db,'design',design)
    finally:
        db.close()
    return identifier


def get(db,key):
    row=db.execute('SELECT payload FROM metadata WHERE name=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def put(db,key,value):
    db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,canonical(value)))


def saved_design(identifier):
    with checkpoint(identifier) as db:
        return get(db,'design')


def saved_studies():
    result=[]
    for path in sorted(ROOT.glob('*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
        try:
            with checkpoint(path.stem) as db:
                design=get(db,'design')
                status=get(db,'status') or {}
                complete=db.execute("SELECT 1 FROM metadata WHERE name='result'").fetchone() is not None
                result.append(dict(id=path.stem,candidates=len(design['candidates']),
                                   seed=design['seed'],complete=complete,done=status.get('done',0)))
        except (ValueError,sqlite3.DatabaseError,TypeError):
            continue
    return result


def seed_for(design,phase,game):
    return (design['seed']+(BLOCK[phase]+game)*SEED_STRIDE)%MODULUS


def compact_summary(matches,details,seats):
    result=summarize(matches,details,seats)
    all_seats=[r for match in matches for rows in match.values() for r in rows]
    anchor=[r for r in all_seats if r['strict']]
    result.update(strict_score=mean(r['score'] for r in anchor),
                  strict_win=mean(r['win'] for r in anchor),
                  actual_banked=[mean(z in r['banked_zones'] for r in all_seats) for z in (1,2,3)])
    return result


def view_keys(row):
    # Fixed matchups compare the intended routes. Adaptive matchups show whether
    # those incentives still work when a seat is free to choose another zone.
    fixed=row['matchups'][:2]
    middle=[]
    upside=[]
    for match in fixed:
        shallow=match['strict_score']
        two,three=match['routes'][1:]
        middle.append(max(0,min(two['score'],three['score'])-shallow,
                          shallow-max(two['score'],three['score'])))
        score_gap=max(0,(two['winning_score'] or 0)-(three['winning_score'] or 0),
                      (match['routes'][0]['winning_score'] or 0)-(three['winning_score'] or 0))
        win_gap=max(0,three['win']-min(two['win'],match['strict_win'])+.001)
        upside.append((score_gap,win_gap,three['winning_score'] or 0))
    return {
        'middle':(mean(middle),abs(mean(m['strict_score']-mean([r['score'] for r in m['routes'][1:]])
                                        for m in fixed))),
        'zone2':(-mean(m['routes'][1]['funnel']['banked']['rate'] for m in fixed),
                 mean(m['score_spread2'] for m in fixed)),
        'zone3':(sum(not m['routes'][2]['winning_score'] for m in fixed),
                 mean(g+20*w for g,w,_ in upside),-mean(s for _,_,s in upside)),
    }


def shortlist(rows,limit):
    ranked=[[row['candidate'] for row in sorted(rows,key=lambda row:(view_keys(row)[view],row['candidate']))]
            for view in ('middle','zone2','zone3')]
    selected={}
    for group in zip(*ranked):
        for candidate in group:
            if candidate!=0:
                selected[candidate]=None
            if len(selected)==limit:
                return list(selected)
    return list(selected)


def play_batch(candidate,design,phase,scenario,rotation,policy,cancel):
    seats=candidate['settings']['players']
    policies={int(depth):POLICY_MENU[label] for depth,label in policy.items()}
    results=[]
    for game in range(rotation*seats,(rotation+1)*seats):
        seed=seed_for(design,phase,game)
        details=[]
        routes=play(candidate['settings'],candidate['board'],seed,game,False,scenario>=2,
                    Counter(),[],cancel,lambda m:details.append(match_metrics(m)),
                    assignment=assignment(seats,scenario,game),policies=policies)
        results.append(dict(seed=seed,game=game,routes=routes,details=details[0]))
    return results


def paired_changes(matches,controls):
    common={m['seed']:m for m in controls}
    output=[]
    for depth in ('1','2','3'):
        pairs=[(m,common[m['seed']]) for m in matches if m['seed'] in common]
        delta=[mean(p['score'] for p in m['routes'][depth])-mean(p['score'] for p in c['routes'][depth])
               for m,c in pairs]
        output.append(dict(mean=mean(delta) if delta else None,
                           interval=interval([[v] for v in delta],signed=True) if delta else [None,None],
                           games=len(delta)))
    return output


class Study:
    def __init__(self,db,progress,cancel):
        self.db=db
        self.design=get(db,'design')
        self.progress=progress
        self.cancel=cancel
        self.done=(get(db,'status') or {}).get('done',0)
        self.candidates=self.design['candidates']

    def measure(self,candidate,phase,rotations,policy=None,controls=None,cache_phase=None):
        policy=policy or {}
        results=[]
        summaries=[]
        for scenario,matchup in enumerate(MATCHUPS):
            matches=[]
            seats=candidate['settings']['players']
            for rotation in range(rotations):
                if self.cancel and self.cancel():
                    raise InterruptedError('Study paused. Completed rotations are saved.')
                key=canonical([candidate['id'],cache_phase or phase,scenario,rotation,policy])
                stored=self.db.execute('SELECT payload FROM batches WHERE key=?',(key,)).fetchone()
                if stored:
                    matches.extend(json.loads(stored[0]))
                    continue
                batch=play_batch(candidate,self.design,phase,scenario,rotation,policy,self.cancel)
                payload=canonical(batch)
                self.done+=len(batch)
                status=dict(phase=f'{(cache_phase or phase).capitalize()} · {matchup}',
                            done=self.done,total=self.design['maximum_matches'])
                with self.db:
                    self.db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?)',
                                    (key,candidate['id'],cache_phase or phase,scenario,canonical(policy),payload))
                    put(self.db,'status',status)
                if self.progress:
                    self.progress(status)
                matches.extend(json.loads(payload))
            summary=compact_summary([{int(k):v for k,v in row['routes'].items()} for row in matches],
                                    [row['details'] for row in matches],seats)
            if controls is not None:
                summary['score_delta']=paired_changes(matches,controls[scenario])
            summaries.append(dict(label=matchup,**summary))
            results.append(matches)
        return dict(candidate=candidate['id'],policy=policy,matchups=summaries),results

    def retune(self,candidate):
        selected={}
        for depth in ('1','2','3'):
            alternatives=[]
            for option in [None,*POLICY_MENU]:
                policy=dict(selected)
                if option is not None:
                    policy[depth]=option
                _,matches=self.measure(candidate,'refine',1,policy,cache_phase='retune')
                rows=[p for group in matches for match in group for p in match['routes'][depth] if not p['strict']]
                if rows:
                    alternatives.append((mean(p['win'] for p in rows),mean(p['score'] for p in rows),option))
            if alternatives:
                option=max(alternatives,key=lambda row:row[:2])[-1]
                if option is not None:
                    selected[depth]=option
        return selected

    def run(self):
        stored=get(self.db,'result')
        if stored:
            return stored
        if self.progress:
            self.progress(dict(phase='Reading checkpoint',done=self.done,total=self.design['maximum_matches']))
        rotations=self.design['rotations']
        screen=[self.measure(c,'screen',rotations['screen'])[0] for c in self.candidates]
        refined=[]
        profiles={}
        for i in [0,*shortlist(screen,12)]:
            c=self.candidates[i]
            # Retuning uses the first refinement rotation. Store the full original
            # profile separately for paired comparison with the adapted profile.
            original=self.measure(c,'refine',rotations['refine'])[0]
            policy=self.retune(c)
            profiles[i]=policy
            refined.append(self.measure(c,'refine',rotations['refine'],policy)[0] if policy else original)
        validations=[]
        original_control=retuned_control=None
        for i in [0,*shortlist(refined,6)]:
            original,raw=self.measure(self.candidates[i],'fresh',rotations['fresh'],controls=original_control)
            retuned,raw_retuned=self.measure(self.candidates[i],'fresh',rotations['fresh'],
                                           profiles[i],retuned_control)
            if i==0:
                original_control,retuned_control=raw,raw_retuned
            validations.append(dict(candidate=i,original=original,retuned=retuned))
        views={view:[row['candidate'] for row in sorted(validations[1:],
                key=lambda item:(view_keys(item['retuned'])[view],item['candidate']))]
               for view in ('middle','zone2','zone3')}
        result=dict(design=self.design,screen=screen,refined=refined,validation=validations,
                    views=views,matches=self.done,
                    seed_stride=SEED_STRIDE,
                    policy_menu={key:dict(asdict(policy),deposit=list(policy.deposit))
                                 for key,policy in POLICY_MENU.items()},
                    seed_blocks={phase:seed_for(self.design,phase,0) for phase in BLOCK})
        with self.db:
            put(self.db,'result',result)
            put(self.db,'status',dict(phase='Complete',done=self.done,total=self.done))
        if self.progress:
            self.progress(dict(phase='Complete',done=self.done,total=self.done))
        return result


def run(identifier,progress=None,cancel=None):
    path=path_for(identifier)
    if not path.is_file():
        raise ValueError('Study checkpoint not found.')
    with path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('This study is running in another simulator process.') from exc
        with checkpoint(identifier) as db:
            return Study(db,progress,cancel).run()


def export_json(identifier):
    with checkpoint(identifier) as db:
        return get(db,'result') or dict(design=get(db,'design'),status=get(db,'status'))


def export_csv(identifier):
    with checkpoint(identifier) as db:
        design=get(db,'design')
        stream=io.StringIO()
        writer=csv.writer(stream)
        writer.writerow(('candidate','stage','matchup','game','seed','policies','settings','map',
                         'seats_by_route','deck_draws','match_minutes'))
        yield stream.getvalue()
        for candidate,phase,scenario,profile,payload in db.execute(
                'SELECT candidate,phase,matchup,profile,payload FROM batches ORDER BY rowid'):
            setup=design['candidates'][candidate]
            stream.seek(0)
            stream.truncate(0)
            for row in json.loads(payload):
                writer.writerow((candidate,phase,MATCHUPS[scenario],row['game'],row['seed'],profile,
                                 canonical(setup['settings']),canonical(setup['board']),
                                 canonical(row['routes']),canonical(row['details']['draws']),
                                 row['details']['minutes']))
            yield stream.getvalue()
