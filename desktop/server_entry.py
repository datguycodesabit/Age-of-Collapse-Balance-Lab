"""Run the app's private loopback server for the lifetime of its launcher."""
import argparse
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

# Isolated Python does not add the script directory to its import path.
sys.path.insert(0,str(Path(__file__).resolve().parent))
from server import Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',required=True,type=int)
    parent=parser.parse_args().parent
    if os.getppid()!=parent:
        return
    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        def stop_with_parent():
            while os.getppid()==parent:
                time.sleep(1)
            server.shutdown()

        threading.Thread(target=stop_with_parent,daemon=True).start()
        print(server.server_port,flush=True)
        server.serve_forever()


if __name__=='__main__':
    main()
