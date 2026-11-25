"""The duckdb server (servers/duckdb): its own code against the real DuckDB engine (inside the image, or a venv from
servers/duckdb/requirements.txt) - DuckDB's own sandbox as the server sets it up (no file outside /work, no '..', no
link out, no extension, the configuration locked), the read-only mode (COPY, EXPORT, ATTACH refused; attached
DuckDB files read-only; scratch tables in memory allowed), DUCKDB_WRITE=1, the time and memory limits, answers within
24,000 characters, the catalog tools, argument checks. The folders are temporary ones the module's ROOTS point at. CI
runs this inside the image too (tests/test_own_servers.py test_duckdb)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "duckdb" / "src" / "server.py"

try:
    import duckdb
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    duckdb = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_duckdb_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_duckdb_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


@unittest.skipIf(duckdb is None, "duckdb and mcp are not installed (servers/duckdb/requirements.txt)")
class DuckDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = fixtures()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="duckdb-test-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.outside = Path(tempfile.mkdtemp(prefix="duckdb-outside-"))
        self.addCleanup(shutil.rmtree, self.outside, True)
        (self.outside / "secret.csv").write_text("secret\nhunter2\n")
        shutil.copy(ROOT / "tests" / "fixtures" / "sales.csv", self.work / "sales.csv")
        shutil.copy(ROOT / "tests" / "fixtures" / "events.jsonl", self.work / "events.jsonl")
        (self.work / "sales.parquet").write_bytes(self.files["sales.parquet"])
        (self.work / "shop.duckdb").write_bytes(self.files["shop.duckdb"])
        os.symlink(self.outside / "secret.csv", self.work / "link.csv")
        self.env = mock.patch.dict(os.environ, {"DUCKDB_DATABASE": "", "DUCKDB_WRITE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.module = None

    def server(self, **env):
        os.environ.update(env)
        module = load()
        module.ROOTS[module.WORK] = str(self.work)
        self.module = module
        return module

    def query(self, sql, **kwargs) -> dict:
        return json.loads(self.module.execute_query(sql, **kwargs))

    def refused(self, sql, text, **kwargs):
        with self.assertRaises(ToolError) as caught:
            self.module.execute_query(sql, **kwargs)
        self.assertIn(text, str(caught.exception))

    def test_files_in_work(self):
        self.server()
        w = self.work
        result = self.query(f"SELECT region, sum(units) AS units FROM '{w}/sales.csv' GROUP BY ALL ORDER BY 1")
        self.assertEqual(result["columns"], ["region", "units"])
        self.assertEqual(result["rows"], [["North", 160], ["South", 156], ["West", 150]])
        self.assertEqual(self.query(f"SELECT count(*) FROM read_parquet('{w}/*.parquet')")["rows"], [[5]])
        self.assertEqual(self.query(f"SELECT user FROM read_json('{w}/events.jsonl') WHERE action = 'upload'")["rows"],
                         [["ana"]])
        described = self.query(f"DESCRIBE SELECT * FROM '{w}/sales.csv'")
        self.assertIn(["price", "DOUBLE", "YES", None, None, None], described["rows"])

    def test_nothing_outside_work(self):
        self.server()
        w = self.work
        for sql in ("SELECT * FROM read_csv('/etc/passwd')", f"SELECT * FROM read_csv('{w}/../{self.outside.name}/x')",
                    f"SELECT * FROM read_csv('{self.outside}/secret.csv')", f"SELECT * FROM read_csv('{w}/link.csv')",
                    "SELECT * FROM read_text('/proc/self/environ')", "SELECT * FROM glob('/etc/*')",
                    f"SELECT * FROM '{w}x/a.csv'"):
            self.refused(sql, "Permission Error")
        names = [row[0] for row in self.query(f"SELECT * FROM glob('{w}/*')")["rows"]]
        self.assertIn(f"{w}/sales.csv", names)

    def test_configuration_locked(self):
        self.server()
        for sql in ("SET enable_external_access = true", "SET lock_configuration = false", "RESET lock_configuration",
                    "SET allowed_directories = ['/']", "SET memory_limit = '64GB'", "SET threads = 64",
                    "SET autoload_known_extensions = true"):
            self.refused(sql, "the configuration has been locked")
        settings = dict((r[0], r[1]) for r in self.query(
            "SELECT name, value FROM duckdb_settings() WHERE name IN ('enable_external_access', 'lock_configuration', "
            "'autoinstall_known_extensions', 'autoload_known_extensions', 'allow_community_extensions', "
            "'allow_unsigned_extensions', 'python_enable_replacements', 'extension_directory', 'threads', "
            "'temp_directory')")["rows"])
        self.assertEqual(settings, {"enable_external_access": "false", "lock_configuration": "true",
                                    "autoinstall_known_extensions": "false", "autoload_known_extensions": "false",
                                    "allow_community_extensions": "false", "allow_unsigned_extensions": "false",
                                    "python_enable_replacements": "false",
                                    "extension_directory": "/nonexistent-extensions", "threads": "2",
                                    "temp_directory": ""})
        memory = self.query("SELECT current_setting('memory_limit')")["rows"][0][0]
        self.assertRegex(memory, r"^4[0-9]{2}\.[0-9] MiB$")  # 512MB as DuckDB shows it

    def test_no_extensions(self):
        self.server(DUCKDB_WRITE="1")
        for sql in ("INSTALL httpfs", "LOAD httpfs", "FORCE INSTALL spatial FROM community", "UPDATE EXTENSIONS",
                    f"LOAD '{self.work}/evil.duckdb_extension'"):
            self.refused(sql, "extensions are never installed or loaded")
        self.refused("SELECT * FROM read_csv('https://example.com/a.csv')", "Permission Error")

    def test_read_only(self):
        self.server(DUCKDB_DATABASE="/work/shop.duckdb")
        w = self.work
        for sql in (f"COPY (SELECT 1) TO '{w}/out.csv'", f"EXPORT DATABASE '{w}/dump'", f"ATTACH '{w}/new.duckdb'",
                    "DETACH shop", f"SELECT 1; COPY (SELECT 1) TO '{w}/out.csv'"):
            self.refused(sql, "this server is read-only")
        self.refused("INSERT INTO orders VALUES ('x', 'y', 'z', 1, 1)", "read-only mode")
        self.refused("DROP TABLE orders", "read-only mode")
        self.assertEqual(sorted(p.name for p in w.iterdir()),
                         ["events.jsonl", "link.csv", "sales.csv", "sales.parquet", "shop.duckdb"])
        scratch = self.query("CREATE TEMP TABLE t AS SELECT 1 AS a; INSERT INTO t VALUES (2); SELECT sum(a) FROM t")
        self.assertEqual(scratch["rows"], [[3]])
        pivot = self.query("PIVOT (SELECT region, quarter, units FROM orders) ON quarter USING sum(units) ORDER BY 1")
        self.assertEqual(pivot["columns"], ["region", "2026-Q1", "2026-Q2"])

    def test_writes_with_duckdb_write(self):
        self.server(DUCKDB_DATABASE="shop.duckdb", DUCKDB_WRITE="1")
        w = self.work
        self.query(f"COPY (SELECT region FROM orders) TO '{w}/regions.csv'")
        self.assertTrue((w / "regions.csv").is_file())
        self.query("INSERT INTO orders VALUES ('East', 'Widget', '2026-Q3', 7, 9.5)")
        self.assertEqual(self.query("SELECT count(*) FROM orders")["rows"], [[6]])
        self.refused(f"COPY (SELECT 1) TO '{self.outside}/x.csv'", "Permission Error")

    def test_database_files(self):
        module = self.server(DUCKDB_DATABASE="/work/shop.duckdb, sales.parquet")
        self.assertEqual(module.database_files(), [(f"{self.work}/shop.duckdb", "shop"),
                                                   (f"{self.work}/sales.parquet", "sales")])
        for bad in ("/etc/x.duckdb", "../x.duckdb", "/work/../etc/x", "/work"):
            with mock.patch.dict(os.environ, {"DUCKDB_DATABASE": bad}):
                with self.assertRaises(SystemExit):
                    module.database_files()
        with mock.patch.dict(os.environ, {"DUCKDB_DATABASE": "1st.duckdb,memory.duckdb"}):
            self.assertEqual([a for _, a in module.database_files()], ["db_1st", "memory_"])

    def test_linked_database_refused(self):
        os.symlink(self.work / "shop.duckdb", self.work / "linked.duckdb")
        self.server(DUCKDB_DATABASE="linked.duckdb")
        self.refused("SELECT 1", "not a regular file")

    def test_catalog_tools(self):
        module = self.server(DUCKDB_DATABASE="shop.duckdb")
        databases = json.loads(module.list_databases())["databases"]
        self.assertEqual([(d["name"], d["readOnly"], d["current"]) for d in databases],
                         [("memory", False, False), ("shop", True, True)])
        tables = json.loads(module.list_tables())
        self.assertEqual([(t["name"], t["type"]) for t in tables["tables"]], [("orders", "table"),
                                                                              ("big_orders", "view")])
        self.assertEqual(tables["tables"][0]["comment"], "Orders by region and quarter")
        columns = json.loads(module.list_columns("orders"))
        self.assertEqual([c["name"] for c in columns["columns"]], ["region", "product", "quarter", "units", "price"])
        self.assertEqual(json.loads(module.list_columns("big_orders", database="shop", schema="main"))["objectType"],
                         "view")
        for call, text in ((lambda: module.list_tables(database="nope"), "there is no database"),
                           (lambda: module.list_tables(schema="nope"), "has no schema"),
                           (lambda: module.list_columns("nope"), "no table or view"),
                           (lambda: module.list_columns("x'; DROP TABLE orders; --"), "no table or view"),
                           (lambda: module.list_columns(""), "table:"),
                           (lambda: module.list_columns("a\nb"), "table:")):
            with self.assertRaises(ToolError) as caught:
                call()
            self.assertIn(text, str(caught.exception))

    def test_bounds(self):
        module = self.server()
        result = self.query("SELECT range FROM range(5000)")
        self.assertEqual(result["rowCount"], 200)
        self.assertTrue(result["truncated"])
        self.assertEqual(self.query("SELECT range FROM range(5000)", max_rows=1000)["rowCount"], 1000)
        wide = module.execute_query("SELECT repeat('x', 1500) AS a, range FROM range(1000)", max_rows=1000)
        self.assertLessEqual(len(wide), module.MAX_CHARS)
        self.assertIn("fit into 24000 characters", wide)
        long_value = self.query("SELECT repeat('y', 100000) AS a")["rows"][0][0]
        self.assertEqual(len(long_value), module.MAX_VALUE)
        blob = self.query("SELECT '\\xAA\\xBB'::BLOB AS b, DATE '2026-11-25' AS d, 1.5::DECIMAL(4,2) AS n, "
                          "[1, 2] AS l, {'k': 'v'} AS s, 'nan'::DOUBLE AS f")["rows"][0]
        self.assertEqual(blob, ["\\xaabb", "2026-11-25", "1.50", [1, 2], {"k": "v"}, "nan"])
        for bad in (0, 1001, True, "10"):
            self.refused("SELECT 1", "max_rows:", max_rows=bad)
        for bad in ("", "   ", "x" * 100_001, "a\x00b"):
            self.refused(bad, "sql:")

    def test_time_and_memory_limits(self):
        module = self.server()
        with mock.patch.object(module, "TIME_LIMIT", 1.0):
            self.refused("SELECT sum(hash(a.range * b.range)) FROM range(100000) a, range(100000) b",
                         "longer than 1 s")
        self.assertEqual(self.query("SELECT 42")["rows"], [[42]])  # the connection survives
        self.refused("SELECT list(range) FROM range(200000000)", "Out of Memory")
        self.assertEqual(self.query("SELECT 43")["rows"], [[43]])

    def test_errors_bounded(self):
        self.server()
        with self.assertRaises(ToolError) as caught:
            self.module.execute_query("SELECT * FROM " + "x" * 5000)
        self.assertLessEqual(len(str(caught.exception)), 2100)


if __name__ == "__main__":
    unittest.main()
