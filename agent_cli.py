#!/usr/bin/env python3
"""Persistent agent matches: create, observe, act. All output is JSON."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

from agent_match import AgentMatch
from zone_decks import DEFAULTS
from dice_rules import DEFAULTS as DICE_DEFAULTS


def write_save(path, match):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name+'.', delete=False) as out:
            temporary = out.name
            json.dump(match.serialize(), out, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('create', 'observe', 'act'))
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--actor', type=int, default=0, help='Seat whose observation to return (zero-based).')
    parser.add_argument('--config', type=Path, help='Create only: JSON with settings and optional board, as exported by the web lab.')
    parser.add_argument('--shared-decks', action='store_true', help='Create using the three shared 50-card decks.')
    parser.add_argument('--dice-rules', action='store_true', help='Create with shared decks, dice combat and repeat banking.')
    parser.add_argument('--command', help='Act only: JSON {actor, revision, action}; omit to read stdin.')
    args = parser.parse_args()
    try:
        # Lock a stable sibling inode, since the save itself is atomically replaced.
        with args.state.with_name(args.state.name+'.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.operation == 'create':
                if args.state.exists():
                    raise ValueError('Match already exists. Choose a new state file.')
                config = json.loads(args.config.read_text()) if args.config else {}
                if not isinstance(config, dict):
                    raise ValueError('Configuration must be an object.')
                settings=config.get('settings',{})
                if args.shared_decks or args.dice_rules:
                    if not isinstance(settings,dict):
                        raise ValueError('Settings must be an object.')
                    defaults=DICE_DEFAULTS if args.dice_rules else DEFAULTS
                    settings={**defaults,**settings,'shared_decks':1}
                    if args.dice_rules:
                        settings['dice_rules']=1
                match = AgentMatch(settings, config.get('board'))
                observation = match.observation(args.actor)
                write_save(args.state, match)
                output = dict(created=True, observation=observation)
            else:
                match = AgentMatch.restore(json.loads(args.state.read_text()))
                # Check the observation seat before committing a command.
                match.observation(args.actor)
                if args.operation == 'act':
                    command = json.loads(args.command if args.command is not None else sys.stdin.read())
                    result = match.submit(command)
                    if result['accepted']:
                        write_save(args.state, match)
                    output = dict(result=result, observation=match.observation(args.actor))
                else:
                    output = dict(observation=match.observation(args.actor))
        print(json.dumps(output, allow_nan=False))
        return 2 if args.operation == 'act' and not output['result']['accepted'] else 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps(dict(error=str(exc))))
        return 1


if __name__ == '__main__':
    sys.exit(main())
