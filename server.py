#!/usr/bin/env python3
"""Local-only simulator. Run: python3 server.py --port 8765"""
import argparse
import json
import mimetypes
import threading
import time
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from engine import (ESCAPE_TEST_SETUP, GEAR_BALANCE_PRICES, METRICS, TARGET_DETAILS, TUNABLE,
                    experiment, search, route_study, settings_from, board_from, board_metadata)
from model import Settings, FIELDS, GEAR, GEAR_EFFECTS, POTIONS
from ev_audit import audit
from balance_study import analyze, PRESET as BALANCE_PRESET
from settings_presets import CATALOG, run_preset
from study_design import NUMERIC, STARTER_AXES, make_design
import large_study
import zone_decks
import dice_rules

ROOT = Path(__file__).parent/'static'
JOBS = {}
LOCK = threading.Lock()
ACTIVE = threading.Semaphore(1)


def launch(kind, settings, specification, board):
    if not ACTIVE.acquire(blocking=False):
        raise ValueError('An experiment is already running. Wait or cancel it first.')
    study_id=None
    try:
        if kind=='large-study':
            study_id=specification.get('resume')
            if study_id:
                large_study.saved_design(study_id)
            else:
                study_id=large_study.create(make_design(settings,board,specification))
    except Exception:
        ACTIVE.release()
        raise
    identifier = uuid.uuid4().hex
    job = dict(id=identifier,state='running',progress=dict(phase='Starting',done=0,total=1))
    if study_id:
        job['study_id']=study_id
    stop = threading.Event()
    with LOCK:
        for old in list(JOBS):
            if len(JOBS) < 8: break
            if JOBS[old]['state'] != 'running': del JOBS[old]
        JOBS[identifier] = dict(**job,stop=stop)

    def progress(value):
        with LOCK: JOBS[identifier]['progress'] = value

    def work():
        try:
            if kind=='search':
                result=search(settings,specification,progress,stop.is_set,board)
            elif kind=='presets':
                result=run_preset(settings,specification,board,progress,stop.is_set)
            elif kind=='large-study':
                result=large_study.run(study_id,progress,stop.is_set)
            elif kind=='study':
                result=route_study(settings,specification,progress,stop.is_set,board)
            elif kind=='audit':
                result=audit(settings,specification,progress,stop.is_set,board)
            elif kind=='balance':
                result=analyze(settings,specification,board,progress,stop.is_set)
            else:
                result=experiment(settings,cancel=stop.is_set,board=board)
            with LOCK: JOBS[identifier].update(state='complete',result=result)
        except InterruptedError:
            with LOCK: JOBS[identifier]['state'] = 'cancelled'
        except (ValueError, TypeError, OverflowError) as exc:
            with LOCK: JOBS[identifier].update(state='error',error=str(exc))
        except Exception:
            with LOCK: JOBS[identifier].update(state='error',error='Experiment failed. See the server terminal.')
            import traceback
            traceback.print_exc()
        finally: ACTIVE.release()
    threading.Thread(target=work,daemon=True).start()
    return job


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep polling out of the terminal.
        if not args or '/api/jobs/' not in str(args[0]): super().log_message(format,*args)

    def send(self, status, body, content_type='application/json'):
        data = json.dumps(body,allow_nan=False).encode() if content_type == 'application/json' else body
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        host = self.headers.get('Host','')
        allowed = {'localhost:%s'%self.server.server_port,'127.0.0.1:%s'%self.server.server_port}
        origin = self.headers.get('Origin')
        if host not in allowed or (origin and origin not in {'http://'+h for h in allowed}):
            self.send(403,{'error':'This app accepts same-origin localhost requests only.'})
            return False
        return True

    def do_GET(self):
        if not self.local_request(): return
        path = urlparse(self.path).path
        if path == '/api/config':
            defaults={**asdict(Settings()),**dice_rules.DEFAULTS,'runs':100}
            return self.send(200,dict(defaults=defaults,legacy_defaults=asdict(Settings()),fields=FIELDS,metrics=METRICS,tunable=sorted(TUNABLE),board=board_metadata(),version=3,
                                      gear={name:dict(price=GEAR[name][0],enabled=GEAR[name][1],effect=effect) for name,effect in GEAR_EFFECTS.items()},
                                      potions=POTIONS,zone_decks=zone_decks.COMPOSITION,items=zone_decks.ITEMS,
                                      gear_balance_prices=GEAR_BALANCE_PRICES,escape_test_setup=ESCAPE_TEST_SETUP,
                                      search_presets=CATALOG,study_axes=NUMERIC,study_starter=STARTER_AXES,
                                      target_details=TARGET_DETAILS))
        if path == '/api/balance-preset':
            return self.send(200,json.loads(BALANCE_PRESET.read_text()))
        if path=='/api/large-studies':
            return self.send(200,large_study.saved_studies())
        if path.startswith('/api/large-studies/'):
            try:
                identifier,kind=path.split('/')[-2:]
                if kind=='json':
                    return self.send(200,large_study.export_json(identifier))
                if kind=='csv':
                    return self.send_study_csv(identifier)
            except ValueError as exc:
                return self.send(404,{'error':str(exc)})
            return self.send(404,{'error':'Unknown study export.'})
        if path.startswith('/api/jobs/'):
            identifier = path.rsplit('/',1)[-1]
            with LOCK:
                job = JOBS.get(identifier)
                public = {k:v for k,v in job.items() if k != 'stop'} if job else None
            return self.send(200,public) if public else self.send(404,{'error':'Experiment not found.'})
        assets = {'/':'index.html','/app.js':'app.js','/large-study.js':'large-study.js',
                  '/styles.css':'styles.css','/cave_balance.json':'cave_balance.json'}
        if path not in assets: return self.send(404,{'error':'Not found.'})
        name = assets[path]
        if not (ROOT/name).is_file(): return self.send(404,{'error':'Balance report is not available.'})
        return self.send(200,(ROOT/name).read_bytes(),mimetypes.guess_type(name)[0]+'; charset=utf-8')

    def do_POST(self):
        if not self.local_request(): return
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 64000: raise ValueError('Request must be 1–64,000 bytes.')
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json': raise ValueError('Send application/json.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('Request must be an object.')
            path = urlparse(self.path).path
            if path == '/api/cancel':
                with LOCK:
                    job = JOBS.get(body.get('id'))
                    if job: job['stop'].set()
                return self.send(200,{'cancelled':bool(job)})
            if path not in ('/api/simulate','/api/search','/api/map','/api/study','/api/audit','/api/balance',
                            '/api/presets','/api/large-study','/api/large-study-preview'):
                return self.send(404,{'error':'Not found.'})
            board = board_from(body.get('board'))
            if path == '/api/map': return self.send(200,board_metadata(board))
            settings = settings_from(body.get('settings',{}))
            kind=path.rsplit('/',1)[1]
            spec = body.get('large-study' if kind=='large-study-preview' else kind,{})
            if not isinstance(spec,dict): raise ValueError('Experiment options must be an object.')
            if kind=='large-study-preview':
                design=make_design(settings,board,spec)
                designs=[]
                for candidate in design['candidates']:
                    farms=board_metadata(board_from(candidate['board']))['farm_distances']
                    distances=[[farm['farm_to_surface'] for farm in farms if farm['zone']==zone]
                               for zone in (1,2,3)]
                    designs.append(dict(id=candidate['id'],axes=candidate['axes'],distances=distances))
                return self.send(200,dict(design,candidates=designs))
            return self.send(202,launch(kind,settings,spec,board))
        except (ValueError,TypeError,OverflowError) as exc:
            return self.send(400,{'error':str(exc)})

    def send_study_csv(self,identifier):
        rows=large_study.export_csv(identifier)
        try:
            header=next(rows)
            self.send_response(200)
            self.send_header('Content-Type','text/csv; charset=utf-8')
            self.send_header('Content-Disposition',f'attachment; filename="study-{identifier}.csv"')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(header.encode())
            for text in rows:
                self.wfile.write(text.encode())
        except (BrokenPipeError,ConnectionResetError):
            pass
        finally:
            rows.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print('Age of Collapse balance lab: http://localhost:%s' % server.server_port,flush=True)
    print('Local only. Press Ctrl+C to stop.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
