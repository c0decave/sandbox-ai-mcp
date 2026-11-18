"""servers/calculator: our own bounded calculator for local models, natively - handshake, tools only, exact arithmetic,
functions, units, dates, and hostile expressions (huge powers and factorials, deep nesting, code) refused fast."""
import json
from pathlib import Path
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "calculator"

try:
    import mcp  # noqa: F401
except ImportError:
    mcp = None

if mcp is not None:
    from test_own_servers import load, result, rpc, session


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (servers/calculator/requirements.txt)")
class Calculator(unittest.TestCase):
    def setUp(self):
        self.module = load("calculator")

    def calc(self, expression):
        return self.module.calculate(expression)

    def test_tools_only(self):
        answers = rpc("calculator", session(("calculate", {"expression": "0.1 + 0.2"})) +
                      [{"jsonrpc": "2.0", "id": 9, "method": "resources/list"}])
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["experimental", "tools"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]),
                         json.loads((FOLDER / "tools.json").read_text())["tools"])
        self.assertEqual(json.loads(answers[2]["result"]["content"][0]["text"])["result"], "0.3")
        self.assertEqual(answers[9]["error"]["code"], -32601)

    def test_exact_arithmetic(self):
        cases = {"0.1 + 0.2": ("0.3", True), "1/3": ("0.333333333333333333333333333333…", False),
                 "(17.5 * 3 + 2) / 4": ("13.625", True), "2^10": ("1024", True), "2**-2": ("0.25", True),
                 "7 % 3": ("1", True), "-7 // 2": ("-4", True), "200 * 15%": ("30", True),
                 "1_000_000 * 3": ("3000000", True), "sqrt(16/9)": ("1.333333333333333333333333333333…", False),
                 "factorial(20)": ("2432902008176640000", True), "comb(52, 5)": ("2598960", True),
                 "gcd(84, 36)": ("12", True), "lcm(4, 6, 10)": ("60", True), "mean(1, 2, 3, 4)": ("2.5", True),
                 "round(2.675, 2)": ("2.68", True), "abs(-3)": ("3", True), "1e3 + 1": ("1001", True),
                 "12 × 3 ÷ 4 − 1": ("8", True)}
        for expression, (expected, exact) in cases.items():
            with self.subTest(expression):
                answer = self.calc(expression)
                self.assertEqual((answer["result"], answer["exact"]), (expected, exact), answer)
        self.assertEqual(self.calc("1/3")["fraction"], "1/3")
        self.assertEqual((self.calc("2**200")["result"], self.calc("2**200")["digits"]), ("1.60693804425899e+60", 61))

    def test_floating_point_functions(self):
        self.assertEqual(self.calc("sqrt(2)")["result"], "1.4142135623731")
        self.assertFalse(self.calc("sqrt(2)")["exact"])
        self.assertEqual(self.calc("sin(pi/2)")["result"], "1")
        self.assertEqual(self.calc("log(8, 2)")["result"], "3")
        self.assertEqual(self.calc("ln(e)")["result"], "1")
        self.assertEqual(self.calc("degrees(atan2(1, 1))")["result"], "45")
        self.assertFalse(self.calc("pi * 2")["exact"])

    def test_errors(self):
        cases = {"1/0": "division by zero", "5 // 0": "division by zero", "0 ** -1": "division by zero",
                 "sqrt(-1)": "not defined", "log(0)": "not defined", "(-8) ** 0.5": "complex",
                 "factorial(2.5)": "whole number", "comb(3, 5)": "comb(n, k)", "foo(1)": "unknown function",
                 "x + 1": "unknown name 'x'", "'a' * 3": "only numbers", "True + 1": "only numbers",
                 "1 +": "not a valid", "": "expression: 1-1000", "1e308 * 10.0": None,
                 "exp(1000)": "too large", "[1, 2]": "not allowed", "lambda: 1": "not allowed",
                 "(1).__class__": "not allowed", "__import__('os')": "unknown function",
                 "abs(1, key=2)": "unknown function", "max()": "at least one argument"}
        for expression, expected in cases.items():
            with self.subTest(expression):
                answer = self.calc(expression)
                if expected is None:
                    self.assertTrue("error" in answer or answer["result"], answer)
                    continue
                self.assertIn(expected, answer.get("error", ""), answer)

    def test_hostile_expressions_are_refused_fast(self):
        hostile = ["9**9**9", "factorial(10**8)", "factorial(451)", "10**1001", "(10**999)*(10**999)",
                   "2**100000", "comb(10**9, 5)", "perm(100000, 50000)", "1" * 1001, "(" * 300 + "1" + ")" * 300,
                   "-" * 900 + "1", "+".join(["1"] * 450), "9" * 1000 + "**2", "1e999", "0.5 ** -100000",
                   "1/" + "3" * 990, "lcm(" + ",".join(["99991"] * 300) + ")"]
        for expression in hostile:
            with self.subTest(expression[:40]):
                started = time.monotonic()
                answer = self.calc(expression)
                self.assertLess(time.monotonic() - started, 2.5)
                self.assertLess(len(json.dumps(answer)), 600)
                if expression not in ("1e999", "1/" + "3" * 990):   # these two are within the limits, shown short
                    self.assertIn("error", answer, answer)

    def test_units(self):
        convert = self.module.convert_units
        self.assertTrue(convert(10, "km", "mi")["result"].startswith("6.21371192237333969617"))
        self.assertEqual(convert("100", "C", "F")["result"], "212")
        self.assertEqual(convert(-40, "F", "C")["result"], "-40")
        self.assertEqual(convert(0, "K", "C")["result"], "-273.15")
        self.assertEqual(convert(1, "GiB", "MB")["result"], "1073.741824")
        self.assertEqual(convert(1, "kWh", "kJ")["result"], "3600")
        self.assertEqual(convert(1, "lb", "g")["result"], "453.59237")
        self.assertEqual(convert(60, "mph", "km/h")["result"], "96.56064")
        self.assertEqual(convert(180, "deg", "rad")["result"][:7], "3.14159")
        self.assertFalse(convert(180, "deg", "rad")["exact"])
        self.assertIn("not convertible", convert(1, "kg", "m")["error"])
        self.assertIn("unknown unit", convert(1, "furlong", "m")["error"])
        self.assertEqual(convert(1, "mb", "kB")["result"], "1000")   # case-insensitive when unambiguous
        self.assertEqual(convert(8, "Mbit", "MB")["result"], "1")
        self.assertIn("below absolute zero", convert(-300, "C", "K")["error"])
        self.assertIn("value: a number", convert("1e9999999", "m", "km")["error"])
        self.assertIn("value: a number", convert(True, "m", "km")["error"])

    def test_dates(self):
        diff = self.module.date_diff("2024-01-31", "2026-11-18")
        self.assertEqual((diff["days"], diff["years_months_days"], diff["end_weekday"]),
                         (1022, [2, 9, 18], "Wednesday"))
        self.assertEqual(self.module.date_diff("2026-11-18", "2026-11-11")["days"], -7)
        self.assertEqual(self.module.date_diff("2026-11-16", "2026-11-23")["business_days"], 5)
        self.assertEqual(self.module.date_add("2024-01-31", months=1)["result"], "2024-02-29")
        self.assertIn("clamped", self.module.date_add("2024-01-31", months=1)["note"])
        self.assertEqual(self.module.date_add("2026-11-18", days=-18, weeks=2)["result"], "2026-11-14")
        self.assertEqual(self.module.date_add("2026-11-18", years=1)["weekday"], "Thursday")
        self.assertIn("not a calendar date", self.module.date_add("2026-02-30")["error"])
        self.assertIn("YYYY-MM-DD", self.module.date_diff("18.11.2026", "2026-11-18")["error"])
        self.assertIn("years 1-9999", self.module.date_add("9999-12-31", days=1)["error"])
        self.assertIn("days: a whole number", self.module.date_add("2026-01-01", days=10 ** 12)["error"])


class Packaging(unittest.TestCase):
    def test_no_network_and_the_shared_lock(self):
        entry = json.loads((FOLDER / "server.json").read_text())
        self.assertEqual(entry["network"], "none")
        self.assertNotIn("hosts", entry)
        lock = (FOLDER / "requirements.txt").read_text().replace("servers/calculator/", "servers/duckduckgo/")
        self.assertEqual(lock, (ROOT / "servers" / "duckduckgo" / "requirements.txt").read_text())
        source = (FOLDER / "src" / "server.py").read_text()
        for forbidden in ("eval(", "exec(", "compile(", "__import__", "subprocess", "open("):
            self.assertNotIn(forbidden, source.replace("never eval", ""))


if __name__ == "__main__":
    unittest.main()
