"""Mini-serveur compatible avec l'interface HTTP de ClickHouse, adossé à chDB (ClickHouse embarqué).

Sert UNIQUEMENT au développement et aux tests sans Docker : il permet de lancer le vrai
`dbt build` (adaptateur dbt-clickhouse) et le producteur contre un moteur ClickHouse réel.
En production, utiliser un vrai serveur ClickHouse (voir docker-compose.yml).

Usage : python devtools/chdb_http_server.py --path .chdb --port 8123
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from chdb import session

FORMAT_RE = re.compile(r"\bFORMAT\s+(\w+)\s*;?\s*$", re.IGNORECASE)
LOCK = threading.Lock()  # une session chDB n'est pas thread-safe


def make_handler(sess):
    class Handler(BaseHTTPRequestHandler):
        def _run(self, body: bytes = b""):
            params = parse_qs(urlparse(self.path).query)
            sql = params.get("query", [""])[0]
            tmp = None
            if not sql and body[:6].upper() == b"INSERT":
                # clickhouse-connect envoie « INSERT … FORMAT X\n » suivi des données binaires dans le corps
                head, _, body = body.partition(b"\n")
                sql = head.decode()
            if body and sql and re.match(r"\s*INSERT\b", sql, re.IGNORECASE):
                # données binaires (Native, RowBinary…) envoyées dans le corps : on les relit via file()
                m = FORMAT_RE.search(sql.strip())
                fd, tmp = tempfile.mkstemp(suffix=".bin")
                os.write(fd, body)
                os.close(fd)
                sql = f"{sql.strip()[:m.start()]} SELECT * FROM file('{tmp}', {m.group(1)})"
            elif body:
                sql = f"{sql}\n{body.decode()}" if sql else body.decode()

            # paramètres serveur {nom:Type} transmis en param_nom=… (substitution typée, usage dev uniquement)
            for key, values in params.items():
                if key.startswith("param_"):
                    literal = "'" + values[0].replace("\\", "\\\\").replace("'", "\\'") + "'"
                    sql = re.sub(r"\{" + re.escape(key[6:]) + r":([^}]+)\}",
                                 lambda m, lit=literal: f"CAST({lit} AS {m.group(1)})", sql)
            if os.environ.get("CHDB_HTTP_DEBUG"):
                print(f"[{self.command}] {self.path[:300]} {sql[:300]!r} body={len(body)}o "
                      f"headers={dict(self.headers)}", flush=True)
            fmt = params.get("default_format", ["TabSeparated"])[0]
            m = FORMAT_RE.search(sql)
            if m:
                fmt, sql = m.group(1), sql[:m.start()]
            try:
                with LOCK:
                    res = sess.query(sql, fmt)
                out = res.bytes() if hasattr(res, "bytes") else bytes(res)
                self.send_response(200)
                self.send_header("X-ClickHouse-Format", fmt)
                self.send_header("X-ClickHouse-Summary", json.dumps({"read_rows": "0", "written_rows": "0"}))
            except Exception as e:  # renvoyé au client comme une erreur ClickHouse
                out = f"Code: 1. DB::Exception: {e}".encode()
                self.send_response(500)
                self.send_header("X-ClickHouse-Exception-Code", "1")
            finally:
                if tmp:
                    os.unlink(tmp)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            self._run()

        def _read_body(self) -> bytes:
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                chunks = []
                while True:
                    size = int(self.rfile.readline().strip().split(b";")[0], 16)
                    if size == 0:
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()
                return b"".join(chunks)
            return self.rfile.read(int(self.headers.get("Content-Length", 0)))

        def do_POST(self):
            self._run(self._read_body())

        def log_message(self, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".chdb")
    ap.add_argument("--port", type=int, default=8123)
    args = ap.parse_args()
    sess = session.Session(args.path)
    print(f"chDB HTTP prêt sur http://127.0.0.1:{args.port} (données : {args.path})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(sess)).serve_forever()


if __name__ == "__main__":
    main()
