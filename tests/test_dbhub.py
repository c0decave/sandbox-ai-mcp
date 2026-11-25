"""The dbhub server (servers/dbhub): its own code offline - the DSN (PostgreSQL and SQLite, the password never in a
message), the read-only classifier (reading keywords first, writing words anywhere outside strings and comments,
escape-hatch functions, one statement), SQLite against a real file (opened read-only, query_only and the authorizer
refusing writes, ATTACH, extension loading and pragma changes even past the classifier; DBHUB_WRITE=1; the time
limit; search_objects), PostgreSQL against a stand-in for pg8000's connection (the startup parameters, TLS modes,
every call in a READ ONLY transaction that is rolled back, the extended protocol for the statement, LIMIT applied in
the server) - and, with SANDBOX_AI_MCP_PG_DSN set (a database CI or a person provides), the same against a real
PostgreSQL. The folders are temporary ones the module's ROOTS point at. CI runs this inside the image too
(tests/test_own_servers.py test_dbhub)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "dbhub" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception
HAVE_PG8000 = importlib.util.find_spec("pg8000") is not None


def load():
    spec = importlib.util.spec_from_file_location("server_dbhub_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_dbhub_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/dbhub/requirements.txt)")
class Dsn(unittest.TestCase):
    def setUp(self):
        self.module = load()

    def test_postgres(self):
        with mock.patch.dict(os.environ, {"DBHUB_PASSWORD": "s@cret"}):
            config = self.module.parse_dsn("postgres://reader@db.example.org:6543/sales?sslmode=require")
        self.assertEqual({k: config[k] for k in ("kind", "host", "port", "user", "password", "database", "sslmode")},
                         {"kind": "postgres", "host": "db.example.org", "port": 6543, "user": "reader",
                          "password": "s@cret", "database": "sales", "sslmode": "require"})
        self.assertNotIn("s@cret", config["shown"])
        self.assertEqual(self.module.parse_dsn("postgresql://u@h/d")["sslmode"], "verify-full")
        self.assertEqual(self.module.parse_dsn("postgresql://u@h")["database"], "u")

    def test_sqlite(self):
        config = self.module.parse_dsn("sqlite:///work/data/app.db")
        self.assertEqual((config["kind"], config["shown"]), ("sqlite", "/work/data/app.db"))

    def test_refused_without_echoing_the_password(self):
        # a password in the DSN is refused (it belongs in DBHUB_PASSWORD) and never echoed; the DSNs that carry one
        # are put together here so that no user:password URL stands in the source
        secret = "u" + ":" + "hunter2" + "@"
        for dsn, text in (("", "DBHUB_DSN is not set"), ("mysql://" + secret + "h/d", "MySQL"),
                          ("postgres://" + secret + "h/d", "no password in the DSN"),
                          ("postgres://u@h:port/d", "port is not a number"),
                          ("postgres://u@h/d?sslmode=allow", "sslmode"),
                          ("postgres://u@h/d?options=-c%20x", "unknown parameters options"),
                          ("postgres://h/d", "no user"), ("sqlite:///etc/passwd", "a SQLite file in /work"),
                          ("sqlite:///work/../etc/x.db", "no '..'"), ("sqlite:///work", "name a SQLite file"),
                          ("postgres://" + secret + "h/d\nx", "control characters")):
            with self.assertRaises(self.module.Refused) as caught:
                self.module.parse_dsn(dsn)
            self.assertIn(text, str(caught.exception), dsn)
            self.assertNotIn("hunter2", str(caught.exception))

    def test_tls_modes(self):
        def config(mode, root=None):
            return {"sslmode": mode, "sslrootcert": root}
        self.assertIs(self.module.ssl_context(config("disable")), False)
        required = self.module.ssl_context(config("require"))
        self.assertEqual((required.verify_mode, required.check_hostname), (ssl.CERT_NONE, False))
        full = self.module.ssl_context(config("verify-full"))
        self.assertEqual((full.verify_mode, full.check_hostname), (ssl.CERT_REQUIRED, True))


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/dbhub/requirements.txt)")
class Classifier(unittest.TestCase):
    def setUp(self):
        self.problem = load().read_only_problem

    def test_reading(self):
        for sql in ("SELECT 1", "  select * from t where note = 'insert into x'", "WITH a AS (SELECT 1) SELECT * FROM a",
                    "EXPLAIN SELECT 1", "SHOW search_path", "VALUES (1)", "TABLE customers",
                    "SELECT comment, created, updated_at FROM t", "SELECT '$$delete$$'", "SELECT $q$ drop $q$",
                    'SELECT "insert" FROM t', "SELECT x::text FROM t -- delete everything", "/* drop */ SELECT 1",
                    "SELECT * FROM orders ORDER BY id OFFSET 5"):
            self.assertIsNone(self.problem(sql, "postgres"), sql)
        for sql in ("PRAGMA table_info('t')", "PRAGMA index_list(t)", "PRAGMA integrity_check"):
            self.assertIsNone(self.problem(sql, "sqlite"), sql)

    def test_writing(self):
        for sql, text in (("DELETE FROM t", "DELETE is not a reading statement"),
                          ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "DELETE"),
                          ("SELECT * INTO copy FROM t", "INTO"), ("EXPLAIN ANALYZE UPDATE t SET a = 1", "UPDATE"),
                          ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
                          ("SELECT set_config('default_transaction_read_only', 'off', false)", "set_config"),
                          ("SELECT lo_export(1, '/tmp/x')", "lo_export"), ("SELECT dblink_exec('x', 'y')", "dblink"),
                          ("SELECT nextval('s')", "nextval"), ("SELECT pg_terminate_backend(1)", "pg_terminate"),
                          ("COMMIT", "COMMIT is not"), ("SET default_transaction_read_only = off", "SET is not"),
                          ("COPY t TO STDOUT", "COPY is not"), ("CALL p()", "CALL is not"), ("DO $$ $$", "DO is not"),
                          ("", "no statement"), ("-- only a comment", "no statement")):
            problem = self.problem(sql, "postgres")
            self.assertIsNotNone(problem, sql)
            self.assertIn(text, problem, sql)
        for sql in ("PRAGMA query_only = 0", "PRAGMA query_only(0)", "PRAGMA writable_schema(1)",
                    "REPLACE INTO t VALUES (1)", "ATTACH 'x' AS y", "SELECT load_extension('x')"):
            self.assertIsNotNone(self.problem(sql, "sqlite"), sql)


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/dbhub/requirements.txt)")
class Sqlite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = fixtures()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dbhub-test-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        (self.work / "shop.sqlite").write_bytes(self.files["shop.sqlite"])
        self.env = mock.patch.dict(os.environ, {"DBHUB_DSN": "sqlite:///work/shop.sqlite", "DBHUB_WRITE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def server(self):
        module = load()
        module.ROOTS[module.WORK] = str(self.work)
        self.addCleanup(module.DB.close)
        return module

    def call(self, function, *args, **kwargs):
        return json.loads(function(*args, **kwargs))

    def refused(self, function, text, *args, **kwargs):
        with self.assertRaises(ToolError) as caught:
            function(*args, **kwargs)
        self.assertIn(text, str(caught.exception))

    def test_reads(self):
        module = self.server()
        result = self.call(module.execute_sql, "SELECT c.name, sum(o.units) AS units FROM orders o JOIN customers c "
                                               "ON c.id = o.customer_id GROUP BY 1 ORDER BY 1")
        self.assertEqual(result["rows"], [["Ana", 160], ["Ben", 245], ["Chen", 61]])
        self.assertEqual(self.call(module.execute_sql, "SELECT comment FROM orders WHERE comment > ''")["rows"],
                         [["rush"], ["gift"]])
        self.assertEqual(self.call(module.execute_sql, "PRAGMA table_info('customers')")["rowCount"], 3)
        limited = self.call(module.execute_sql, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r "
                                                "WHERE n < 5000) SELECT n FROM r", max_rows=10)
        self.assertEqual((limited["rowCount"], limited["truncated"]), (10, True))

    def test_read_only_layers(self):
        module = self.server()
        for sql, text in (("DELETE FROM orders", "this server is read-only"),
                          ("SELECT 1; DELETE FROM orders", "one statement per call"),
                          ("PRAGMA query_only = OFF", "read-only"), ("ATTACH '/etc/passwd' AS p", "read-only"),
                          ("SELECT load_extension('/tmp/x.so')", "load_extension")):
            self.refused(module.execute_sql, text, sql)
        # past the classifier: the engine refuses (query_only, the authorizer, the read-only file)
        for sql in ("DELETE FROM orders", "CREATE TABLE x (a)", "PRAGMA query_only = OFF", "ATTACH ':memory:' AS m",
                    "INSERT INTO customers (name) VALUES ('Eve')", "SELECT load_extension('x')"):
            with self.assertRaises(sqlite3.Error, msg=sql):
                module.DB.run(sql, user_sql=True)
        self.assertEqual(self.call(module.execute_sql, "SELECT count(*) FROM orders")["rows"], [[5]])

    def test_writes_with_dbhub_write(self):
        os.environ["DBHUB_WRITE"] = "1"
        module = self.server()
        self.assertEqual(self.call(module.execute_sql, "INSERT INTO customers (name) VALUES ('Eve')")["rowsAffected"],
                         1)
        self.assertEqual(self.call(module.execute_sql, "SELECT count(*) FROM customers")["rows"], [[4]])
        self.refused(module.execute_sql, "not authorized", "ATTACH ':memory:' AS m")
        self.refused(module.execute_sql, "not authorized", "SELECT load_extension('x')")

    def test_link_and_missing_file(self):
        os.symlink(self.work / "shop.sqlite", self.work / "link.sqlite")
        os.environ["DBHUB_DSN"] = "sqlite:///work/link.sqlite"
        self.refused(self.server().execute_sql, "not a regular file", "SELECT 1")
        os.environ["DBHUB_DSN"] = "sqlite:///work/missing.sqlite"
        self.refused(self.server().execute_sql, "does not exist", "SELECT 1")

    def test_time_limit(self):
        module = self.server()
        with mock.patch.object(module, "TIME_LIMIT", 1):
            self.refused(module.execute_sql, "longer than 1 s",
                         "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r")
        self.assertEqual(self.call(module.execute_sql, "SELECT 42")["rows"], [[42]])

    def test_search_objects(self):
        module = self.server()
        tables = self.call(module.search_objects, "table")
        self.assertEqual([o["name"] for o in tables["objects"]], ["customers", "orders"])
        columns = self.call(module.search_objects, "column", pattern="%id", table="orders", detail_level="summary")
        self.assertEqual([(o["name"], o["type"]) for o in columns["objects"]], [("id", "INTEGER"),
                                                                                ("customer_id", "INTEGER")])
        index = self.call(module.search_objects, "index", detail_level="full")["objects"][0]
        self.assertEqual(index["definition"], "CREATE INDEX orders_customer ON orders(customer_id)")
        self.assertEqual(self.call(module.search_objects, "view")["objects"], [{"schema": "main",
                                                                               "name": "big_orders"}])
        self.assertEqual(self.call(module.search_objects, "function")["count"], 0)
        self.assertEqual(self.call(module.search_objects, "column", limit=2)["truncated"], True)
        for kwargs, text in (({"object_type": "trigger"}, "object_type:"),
                             ({"object_type": "table", "detail_level": "all"}, "detail_level:"),
                             ({"object_type": "table", "limit": 0}, "limit:"),
                             ({"object_type": "table", "table": "orders"}, "table: only for"),
                             ({"object_type": "table", "schema": "public"}, "schema main only"),
                             ({"object_type": "table", "pattern": "a\nb"}, "pattern:")):
            self.refused(module.search_objects, text, **kwargs)

    def test_bounds(self):
        module = self.server()
        wide = module.execute_sql("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 1000) "
                                  "SELECT n, printf('%.1500c', 'x') FROM r", max_rows=1000)
        self.assertLessEqual(len(wide), module.MAX_CHARS)
        self.assertIn("fit into 24000 characters", wide)
        value = self.call(module.execute_sql, "SELECT printf('%.9000c', 'y'), x'00ff'")["rows"][0]
        self.assertEqual((len(value[0]), value[1]), (module.MAX_VALUE, "\\x00ff"))
        for bad in (0, 1001, True):
            self.refused(module.execute_sql, "max_rows:", "SELECT 1", max_rows=bad)
        self.refused(module.execute_sql, "sql:", "")
        self.refused(module.execute_sql, "sql:", "x" * 100_001)


class FakePg:
    """Stands in for pg8000.native.Connection: records what is sent, answers rows."""

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs, self.sent = args, kwargs, []
        self._context = None

    class Context:
        def __init__(self, rows, columns):
            self.rows, self.columns, self.row_count = rows, columns, len(rows or [])

    def run(self, sql, **params):
        self.sent.append(("run", sql, params))
        self._context = self.Context([], [{"name": "x"}] if params else [])
        return self._context.rows

    def execute_unnamed(self, sql, vals=(), oids=(), stream=None):
        self.sent.append(("unnamed", sql))
        if "boom" in sql:
            raise RuntimeError("boom")
        return self.Context([[n] for n in range(3)], [{"name": "n"}])

    def close(self):
        self.sent.append(("close",))


@unittest.skipIf(mcp is None or not HAVE_PG8000, "pg8000 is not installed (servers/dbhub/requirements.txt)")
class PostgresStandIn(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DBHUB_DSN": "postgres://reader@db.example.org/sales",
                                                "DBHUB_PASSWORD": "pw", "DBHUB_WRITE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.made = []

        def connect(*args, **kwargs):
            self.made.append(FakePg(*args, **kwargs))
            return self.made[-1]
        patcher = mock.patch("pg8000.native.Connection", connect)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_read_only_session_and_transaction(self):
        module = load()
        result = json.loads(module.execute_sql("SELECT n FROM t ORDER BY n;", max_rows=2))
        self.assertEqual((result["rows"], result["truncated"]), ([[0], [1]], True))
        con = self.made[0]
        self.assertEqual((con.args, con.kwargs["password"]), (("reader",), "pw"))
        self.assertEqual(con.kwargs["startup_params"], {"statement_timeout": "30000",
                                                        "idle_in_transaction_session_timeout": "60000",
                                                        "default_transaction_read_only": "on"})
        self.assertEqual(con.kwargs["application_name"], "sandbox-ai-mcp-dbhub")
        self.assertTrue(con.kwargs["ssl_context"].check_hostname)
        self.assertEqual(con.sent, [("run", "START TRANSACTION READ ONLY", {}),
                                    ("unnamed", "SELECT * FROM (\nSELECT n FROM t ORDER BY n\n) AS dbhub_limited "
                                                "LIMIT 3"),
                                    ("run", "ROLLBACK", {})])

    def test_explain_not_wrapped_and_errors_rolled_back(self):
        module = load()
        module.execute_sql("EXPLAIN SELECT 1")
        self.assertEqual(self.made[0].sent[1], ("unnamed", "EXPLAIN SELECT 1"))
        with self.assertRaises(ToolError):
            module.execute_sql("SELECT 'boom'")
        self.assertEqual(self.made[0].sent[-1], ("run", "ROLLBACK", {}))

    def test_writes_committed_with_dbhub_write(self):
        os.environ["DBHUB_WRITE"] = "1"
        module = load()
        module.execute_sql("UPDATE t SET a = 1")
        con = self.made[0]
        self.assertNotIn("default_transaction_read_only", con.kwargs["startup_params"])
        self.assertEqual(con.sent, [("run", "START TRANSACTION", {}), ("unnamed", "UPDATE t SET a = 1"),
                                    ("run", "COMMIT", {})])

    def test_catalog_queries_read_only_with_bound_parameters(self):
        os.environ["DBHUB_WRITE"] = "1"
        module = load()
        module.search_objects("table", schema="x'; DROP TABLE t; --")
        sent = self.made[0].sent
        self.assertEqual(sent[0], ("run", "START TRANSACTION READ ONLY", {}))
        self.assertEqual(sent[1][2], {"schema": "x'; DROP TABLE t; --"})
        self.assertNotIn("DROP", sent[1][1])


@unittest.skipUnless(mcp is not None and HAVE_PG8000 and os.environ.get("SANDBOX_AI_MCP_PG_DSN"),
                     "SANDBOX_AI_MCP_PG_DSN names no PostgreSQL to test against")
class RealPostgres(unittest.TestCase):
    """Against a real PostgreSQL (a throwaway database: the test creates and drops a table, with DBHUB_WRITE=1);
    SANDBOX_AI_MCP_PG_DSN without the password, SANDBOX_AI_MCP_PG_PASSWORD with it."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DBHUB_DSN": os.environ["SANDBOX_AI_MCP_PG_DSN"], "DBHUB_WRITE": "1",
                                                "DBHUB_PASSWORD": os.environ.get("SANDBOX_AI_MCP_PG_PASSWORD", "")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_read_only_holds_in_the_engine(self):
        writer = load()
        writer.execute_sql("CREATE TABLE IF NOT EXISTS dbhub_test (id int)")
        self.addCleanup(lambda: (writer.execute_sql("DROP TABLE IF EXISTS dbhub_test"), writer.DB.close()))
        os.environ["DBHUB_WRITE"] = ""
        reader = load()
        self.addCleanup(reader.DB.close)
        self.assertEqual(json.loads(reader.execute_sql("SELECT count(*) FROM dbhub_test"))["rows"], [[0]])
        with self.assertRaises(Exception) as caught:
            reader.DB.run("INSERT INTO dbhub_test VALUES (1)", user_sql=True)
        self.assertIn("25006", str(caught.exception))  # read_only_sql_transaction
        with self.assertRaises(Exception):
            reader.DB.run("SELECT 1; INSERT INTO dbhub_test VALUES (1)", user_sql=True)  # extended protocol: one
        tables = json.loads(reader.search_objects("table", pattern="dbhub%", detail_level="summary"))["objects"]
        self.assertEqual(tables[0]["name"], "dbhub_test")


if __name__ == "__main__":
    unittest.main()
