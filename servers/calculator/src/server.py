#!/usr/bin/env python3
"""Calculator MCP server (sandbox-ai-mcp, our own): exact arithmetic, unit conversion and date arithmetic for agents on
small local models, which get all three wrong - every operation bounded in size and time.

Tools:
    - calculate: an arithmetic expression (+ - * / // % **, parentheses, functions such as sqrt, log, sin,
      factorial, gcd, comb), exact with fractions while it can be (0.1 + 0.2 is 0.3), else floating point
    - convert_units: a value from one unit to another (length, area, volume, mass, time, speed, temperature, data,
      energy, power, pressure, angle)
    - date_diff: the days (and weeks, months, years) between two dates
    - date_add: a date plus or minus days, weeks, months and years, with its weekday

No network, nothing read or written. The expression is parsed with Python's ast and evaluated by a small interpreter
of its own (never eval): only numbers, the listed operators, functions and constants; every intermediate result is
checked against size limits before it is computed (no 9**9**9, no factorial(10**8)), and a whole calculation has a
time limit.
"""

from __future__ import annotations

import ast
import datetime as dt
import math
import operator
import re
import signal
import sys
import threading
from fractions import Fraction

from mcp.server.fastmcp import FastMCP

MAX_EXPRESSION = 1000      # characters
MAX_NODES = 400            # nodes of the parsed expression
MAX_DIGITS = 1000          # decimal digits of an exact integer, numerator or denominator
MAX_FACTORIAL = 450        # 450! has 1,000 digits
MAX_COMB = 10_000          # n of comb and perm
TIME_LIMIT = 2.0           # seconds for one calculation
FLOAT_DIGITS = 15          # significant digits shown of a floating-point result

mcp = FastMCP("calculator-mcp", instructions=(
    "Exact arithmetic, unit conversion and date arithmetic: use these instead of computing in your head. calculate "
    "takes an expression such as (17.5 * 3 + 2) / 4 or sqrt(2) * pi; convert_units a value and two units; date_diff "
    "and date_add take dates as YYYY-MM-DD."))


class CalcError(ValueError):
    """An expression, unit or date that is not accepted, or a result beyond the limits; the text says why."""


# -- calculate ------------------------------------------------------------------------------------------------------------

def _digits(value: int) -> int:
    """Decimal digits of |VALUE| (estimated from its bits, without converting it)."""
    return int(abs(value).bit_length() * 0.30103) + 1


def _check(value):
    """VALUE when it is within the limits, else CalcError."""
    if isinstance(value, Fraction):
        if _digits(value.numerator) > MAX_DIGITS or _digits(value.denominator) > MAX_DIGITS:
            raise CalcError(f"an exact intermediate result has more than {MAX_DIGITS} digits")
    elif isinstance(value, float):
        if math.isnan(value):
            raise CalcError("the result is not a number (NaN)")
        if math.isinf(value):
            raise CalcError("the result is too large (overflow to infinity)")
    elif isinstance(value, complex):
        raise CalcError("complex results are not supported")
    return value


def _float(value) -> float:
    try:
        return float(value)
    except OverflowError:
        raise CalcError("a number is too large for floating point") from None


def _power(base, exponent):
    if isinstance(exponent, Fraction) and exponent.denominator == 1 and isinstance(base, Fraction):
        n = exponent.numerator
        if abs(n) > 100_000:
            raise CalcError("an exponent is too large (at most 100,000 for exact powers)")
        if base == 0 and n < 0:
            raise CalcError("division by zero (0 to a negative power)")
        for part in (base.numerator, base.denominator):
            if part not in (0, 1, -1) and math.log10(abs(part)) * abs(n) > MAX_DIGITS:
                raise CalcError(f"the power would have more than {MAX_DIGITS} digits")
        return _check(base ** n)
    b, e = _float(base), _float(exponent)
    if b < 0 and not float(e).is_integer():
        raise CalcError("a negative number to a fractional power is complex (not supported)")
    if b == 0 and e < 0:
        raise CalcError("division by zero (0 to a negative power)")
    try:
        return _check(math.pow(b, e))
    except OverflowError:
        raise CalcError("the result is too large (overflow)") from None


def _divide(a, b, kind):
    if b == 0:
        raise CalcError("division by zero")
    if kind == "true":
        if isinstance(a, Fraction) and isinstance(b, Fraction):
            return _check(a / b)
        return _check(_float(a) / _float(b))
    if kind == "floor":
        return _check(Fraction(math.floor(a / b)) if isinstance(a, Fraction) and isinstance(b, Fraction)
                      else float(math.floor(_float(a) / _float(b))))
    if isinstance(a, Fraction) and isinstance(b, Fraction):
        return _check(a % b)
    return _check(_float(a) % _float(b))


def _integer(value, what: str) -> int:
    if isinstance(value, Fraction) and value.denominator == 1:
        return value.numerator
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    raise CalcError(f"{what} needs a whole number")


def _factorial(value):
    n = _integer(value, "factorial")
    if not 0 <= n <= MAX_FACTORIAL:
        raise CalcError(f"factorial takes 0 to {MAX_FACTORIAL}")
    return Fraction(math.factorial(n))


def _comb(n, k, kind):
    n, k = _integer(n, kind), _integer(k, kind)
    if not 0 <= k <= n <= MAX_COMB:
        raise CalcError(f"{kind}(n, k) takes 0 <= k <= n <= {MAX_COMB}")
    return _check(Fraction(math.comb(n, k) if kind == "comb" else math.perm(n, k)))


def _real(function):
    """A one-argument function of floats, its domain errors as CalcError."""
    def run(value):
        try:
            return _check(float(function(_float(value))))
        except ValueError:
            raise CalcError(f"{function.__name__} is not defined for {_show(value)}") from None
        except OverflowError:
            raise CalcError(f"{function.__name__}: the result is too large") from None
    return run


def _sqrt(value):
    if isinstance(value, Fraction) and value >= 0:
        top, bottom = math.isqrt(value.numerator), math.isqrt(value.denominator)
        if top * top == value.numerator and bottom * bottom == value.denominator:
            return Fraction(top, bottom)  # an exact square root stays exact
    return _real(math.sqrt)(value)


def _round(value, places=None):
    if places is None:
        return Fraction(round(value)) if isinstance(value, Fraction) else _check(float(round(_float(value))))
    digits = _integer(places, "round's places")
    if not -20 <= digits <= 50:
        raise CalcError("round takes -20 to 50 places")
    return _check(round(value, digits)) if isinstance(value, Fraction) else _check(round(_float(value), digits))


def _log(value, base=None):
    if base is None:
        return _real(math.log)(value)
    try:
        return _check(math.log(_float(value), _float(base)))
    except (ValueError, ZeroDivisionError):
        raise CalcError("log is not defined for these arguments") from None


def _many(function, name):
    def run(*values):
        if not values:
            raise CalcError(f"{name} needs at least one argument")
        return _check(function(values))
    return run


def _gcd(*values):
    return Fraction(math.gcd(*[_integer(v, "gcd") for v in values]))


def _lcm(*values):
    return _check(Fraction(math.lcm(*[_integer(v, "lcm") for v in values])))


FUNCTIONS = {
    "sqrt": _sqrt, "cbrt": _real(math.cbrt), "exp": _real(math.exp), "ln": _real(math.log), "log": _log,
    "log10": _real(math.log10), "log2": _real(math.log2),
    "sin": _real(math.sin), "cos": _real(math.cos), "tan": _real(math.tan), "asin": _real(math.asin),
    "acos": _real(math.acos), "atan": _real(math.atan), "sinh": _real(math.sinh), "cosh": _real(math.cosh),
    "tanh": _real(math.tanh), "degrees": _real(math.degrees), "radians": _real(math.radians),
    "atan2": lambda y, x: _check(math.atan2(_float(y), _float(x))),
    "hypot": lambda *v: _check(math.hypot(*[_float(x) for x in v])),
    "abs": lambda v: abs(v), "floor": lambda v: Fraction(math.floor(v)), "ceil": lambda v: Fraction(math.ceil(v)),
    "round": _round, "trunc": lambda v: Fraction(math.trunc(v)), "factorial": _factorial,
    "comb": lambda n, k: _comb(n, k, "comb"), "perm": lambda n, k: _comb(n, k, "perm"),
    "gcd": _gcd, "lcm": _lcm,
    "min": _many(min, "min"), "max": _many(max, "max"),
    "sum": _many(lambda v: sum(v, Fraction(0)) if all(isinstance(x, Fraction) for x in v) else math.fsum(map(_float, v)),
                 "sum"),
    "mean": _many(lambda v: (sum(v, Fraction(0)) / len(v)) if all(isinstance(x, Fraction) for x in v)
                  else math.fsum(map(_float, v)) / len(v), "mean"),
}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}


class Evaluator:
    """Evaluates a parsed expression: numbers as exact Fractions while only exact operations meet them, floats once
    an irrational function or constant (or a float power) is involved."""

    def __init__(self, deadline):
        self.deadline = deadline
        self.inexact = False

    def __call__(self, node):
        if self.deadline.is_set():
            raise CalcError(f"the calculation took longer than {TIME_LIMIT:g} s")
        method = getattr(self, "visit_" + type(node).__name__, None)
        if method is None:
            raise CalcError(f"not allowed in an expression: {type(node).__name__}")
        return method(node)

    def visit_Expression(self, node):  # noqa: N802
        return self(node.body)

    def visit_Constant(self, node):  # noqa: N802
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CalcError("only numbers are allowed (no text, no True/False)")
        if isinstance(value, int):
            return _check(Fraction(value))
        if id(node) in self.literal:
            return _check(self.literal[id(node)])
        if math.isinf(value) or math.isnan(value):
            raise CalcError("a number is too large")
        return _check(Fraction(repr(value)))

    def visit_Name(self, node):  # noqa: N802
        if node.id in CONSTANTS:
            self.inexact = True
            return CONSTANTS[node.id]
        raise CalcError(f"unknown name {node.id!r}: constants are pi, e and tau; functions need parentheses")

    def visit_UnaryOp(self, node):  # noqa: N802
        value = self(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise CalcError("only + and - are allowed before a number")

    def visit_BinOp(self, node):  # noqa: N802
        left, right = self(node.left), self(node.right)
        op = type(node.op)
        if op in OPERATORS:
            if isinstance(left, float) or isinstance(right, float):
                return _check(OPERATORS[op](_float(left), _float(right)))
            return _check(OPERATORS[op](left, right))
        if op is ast.Div:
            return _divide(left, right, "true")
        if op is ast.FloorDiv:
            return _divide(left, right, "floor")
        if op is ast.Mod:
            return _divide(left, right, "mod")
        if op is ast.Pow:
            result = _power(left, right)
            self.inexact |= isinstance(result, float)
            return result
        raise CalcError("operators are + - * / // % and ** (or ^)")

    def visit_Call(self, node):  # noqa: N802
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
            raise CalcError(f"unknown function; functions are: {', '.join(sorted(FUNCTIONS))}")
        arguments = [self(argument) for argument in node.args]
        try:
            result = FUNCTIONS[node.func.id](*arguments)
        except TypeError:
            raise CalcError(f"{node.func.id}: wrong number of arguments") from None
        self.inexact |= isinstance(result, float)
        return result


def _show(value) -> str:
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return str(value.numerator)
        return f"{value.numerator}/{value.denominator}"
    return repr(value)


def _decimal(value: Fraction, digits: int = 30) -> str:
    """VALUE as a decimal string: exact when it terminates within DIGITS places, else rounded (marked with …)."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, rest = divmod(value.numerator, value.denominator)
    if rest == 0:
        return f"{sign}{whole}"
    places = []
    for _ in range(digits):
        rest *= 10
        digit, rest = divmod(rest, value.denominator)
        places.append(str(digit))
        if rest == 0:
            return f"{sign}{whole}." + "".join(places)
    return f"{sign}{whole}." + "".join(places) + "…"


def evaluate(expression: str) -> dict:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPRESSION:
        raise CalcError(f"expression: 1-{MAX_EXPRESSION} characters")
    text = expression.strip().replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-")
    text = re.sub(r"(?<=\d)_(?=\d)", "", text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(.])", r"(\1/100)", text)  # 15% -> (15/100); 7 % 3 stays modulo
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError):
        raise CalcError("expression: not a valid arithmetic expression") from None
    except (RecursionError, MemoryError):
        raise CalcError("expression: nested too deeply") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise CalcError(f"expression: too long (at most {MAX_NODES} parts)")
    deadline = threading.Event()
    timer = threading.Timer(TIME_LIMIT, deadline.set)
    timer.daemon = True
    evaluator = Evaluator(deadline)
    # decimal literals as written (0.1 is 1/10, not the float nearest to it)
    evaluator.literal = {}
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            source = ast.get_source_segment(text, node) or repr(node.value)
            if re.fullmatch(r"\d*\.?\d*(?:[eE][+-]?\d{1,3})?", source.replace("_", "")):
                try:
                    evaluator.literal[id(node)] = Fraction(source.replace("_", ""))
                except (ValueError, ZeroDivisionError):
                    pass
                else:
                    if _digits(evaluator.literal[id(node)].numerator) > MAX_DIGITS or \
                            _digits(evaluator.literal[id(node)].denominator) > MAX_DIGITS:
                        raise CalcError(f"a number has more than {MAX_DIGITS} digits")
    timer.start()
    try:
        value = evaluator(tree)
    except RecursionError:
        raise CalcError("expression: nested too deeply") from None
    except (OverflowError, MemoryError):
        raise CalcError("the result is too large") from None
    except ZeroDivisionError:
        raise CalcError("division by zero") from None
    finally:
        timer.cancel()
    shown = expression.strip()
    answer = {"expression": shown if len(shown) <= 200 else shown[:199] + "…"}
    if isinstance(value, Fraction):
        answer["result"] = _decimal(value)
        answer["exact"] = not answer["result"].endswith("…")
        if value.denominator != 1 and len(_show(value)) <= 200:
            answer["fraction"] = _show(value)
        if value.denominator == 1 and len(answer["result"].lstrip("-")) > 60:
            whole = answer["result"].lstrip("-")   # a long integer: shown rounded, with its length
            sign = "-" if value < 0 else ""
            answer["result"] = f"{sign}{whole[0]}.{whole[1:FLOAT_DIGITS]}e+{len(whole) - 1}"
            answer["digits"] = len(whole)
            answer["exact"] = False
            answer["note"] = "an integer of more than 60 digits is shown rounded"
    else:
        answer["result"] = f"{value:.{FLOAT_DIGITS}g}"
        answer["exact"] = False
    if evaluator.inexact and answer.get("exact"):
        answer["exact"] = False
    return answer


# -- convert_units --------------------------------------------------------------------------------------------------------

#: unit -> (dimension, factor to the dimension's base unit) - exact factors as Fractions
UNITS: dict = {}


def _units(dimension, table):
    for names, factor in table:
        for name in names.split("|"):
            UNITS[name] = (dimension, Fraction(factor))


_units("length", [("m|meter|meters|metre|metres", 1), ("km|kilometer|kilometers|kilometre", 1000),
                  ("cm|centimeter|centimeters", "0.01"), ("mm|millimeter|millimeters", "0.001"),
                  ("um|µm|micrometer|micrometers", "0.000001"), ("nm|nanometer|nanometers", "1e-9"),
                  ("in|inch|inches", "0.0254"), ("ft|foot|feet", "0.3048"), ("yd|yard|yards", "0.9144"),
                  ("mi|mile|miles", "1609.344"), ("nmi|nautical_mile|nautical_miles", 1852),
                  ("au|astronomical_unit", 149597870700), ("ly|light_year|light_years", 9460730472580800)])
_units("area", [("m2|sqm|square_meter|square_meters", 1), ("km2|square_kilometer", 1000000),
                ("cm2|square_centimeter", "0.0001"), ("ha|hectare|hectares", 10000), ("a|are", 100),
                ("ft2|sqft|square_foot|square_feet", "0.09290304"), ("in2|square_inch", "0.00064516"),
                ("acre|acres", "4046.8564224"), ("mi2|square_mile", "2589988.110336")])
_units("volume", [("l|liter|liters|litre|litres", 1), ("ml|milliliter|milliliters", "0.001"),
                  ("cl|centiliter", "0.01"), ("dl|deciliter", "0.1"), ("m3|cubic_meter", 1000),
                  ("cm3|cc|cubic_centimeter", "0.001"), ("gal|gallon|gallons|us_gallon", "3.785411784"),
                  ("qt|quart|quarts", "0.946352946"), ("pt|pint|pints", "0.473176473"),
                  ("cup|cups", "0.2365882365"), ("floz|fl_oz|fluid_ounce", "0.0295735295625"),
                  ("imp_gal|imperial_gallon", "4.54609"), ("tbsp|tablespoon", "0.01478676478125"),
                  ("tsp|teaspoon", "0.00492892159375")])
_units("mass", [("kg|kilogram|kilograms", 1), ("g|gram|grams", "0.001"), ("mg|milligram|milligrams", "0.000001"),
                ("t|tonne|tonnes|metric_ton", 1000), ("lb|lbs|pound|pounds", "0.45359237"),
                ("oz|ounce|ounces", "0.028349523125"), ("st|stone", "6.35029318"),
                ("short_ton|us_ton", "907.18474")])
_units("time", [("s|sec|second|seconds", 1), ("ms|millisecond|milliseconds", "0.001"),
                ("us|µs|microsecond|microseconds", "0.000001"), ("ns|nanosecond|nanoseconds", "1e-9"),
                ("min|minute|minutes", 60), ("h|hr|hour|hours", 3600), ("d|day|days", 86400),
                ("week|weeks|wk", 604800), ("year|years|yr", 31557600)])  # a Julian year (365.25 days)
_units("speed", [("m/s|mps", 1), ("km/h|kmh|kph", Fraction(1000, 3600)), ("mph|mi/h", Fraction(1609344, 3600000)),
                 ("kn|knot|knots", Fraction(1852, 3600)), ("ft/s|fps", "0.3048")])
_units("data", [("b|bit|bits", Fraction(1, 8)), ("B|byte|bytes", 1), ("kB|KB|kilobyte", 1000),
                ("MB|megabyte", 10 ** 6), ("GB|gigabyte", 10 ** 9), ("TB|terabyte", 10 ** 12),
                ("PB|petabyte", 10 ** 15), ("KiB|kibibyte", 1024), ("MiB|mebibyte", 1024 ** 2),
                ("GiB|gibibyte", 1024 ** 3), ("TiB|tebibyte", 1024 ** 4), ("PiB|pebibyte", 1024 ** 5),
                ("kbit|kilobit", 125), ("Mbit|megabit", 125000), ("Gbit|gigabit", 125000000)])
_units("energy", [("J|joule|joules", 1), ("kJ|kilojoule", 1000), ("cal|calorie", "4.184"),
                  ("kcal|kilocalorie", 4184), ("Wh|watt_hour", 3600), ("kWh|kilowatt_hour", 3600000),
                  ("eV|electronvolt", "1.602176634e-19"), ("BTU|btu", "1055.05585262")])
_units("power", [("W|watt|watts", 1), ("kW|kilowatt", 1000), ("MW|megawatt", 10 ** 6),
                 ("hp|horsepower", "745.69987158227022"), ("PS|metric_horsepower", "735.49875")])
_units("pressure", [("Pa|pascal", 1), ("hPa|hectopascal", 100), ("kPa|kilopascal", 1000), ("bar", 100000),
                    ("mbar|millibar", 100), ("atm|atmosphere", 101325), ("psi", "6894.757293168361"),
                    ("mmHg|torr", "133.322387415")])
_units("angle", [("rad|radian|radians", 1), ("deg|degree|degrees|°", Fraction(math.pi).limit_denominator(10 ** 15) / 180),
                 ("grad|gon", Fraction(math.pi).limit_denominator(10 ** 15) / 200),
                 ("turn|turns|rev", Fraction(math.pi).limit_denominator(10 ** 15) * 2)])
TEMPERATURES = {"c": "C", "°c": "C", "celsius": "C", "degc": "C", "f": "F", "°f": "F", "fahrenheit": "F",
                "degf": "F", "k": "K", "kelvin": "K"}


def _unit(name: str):
    if not isinstance(name, str) or not name.strip() or len(name) > 40:
        raise CalcError("unit: a unit name such as km, mi, kg, lb, GiB, kWh, C or F")
    key = name.strip().replace(" ", "_").replace("²", "2").replace("³", "3")
    if key.lower() in TEMPERATURES:
        return ("temperature", TEMPERATURES[key.lower()])
    if key in UNITS:
        return UNITS[key]
    lowered = {k.lower(): v for k, v in UNITS.items() if k.lower() == key.lower()}
    if len({v for v in lowered.values()}) == 1:
        return next(iter(lowered.values()))
    raise CalcError(f"unknown unit {name.strip()[:40]!r}")


def _number(value) -> Fraction:
    if isinstance(value, bool):
        raise CalcError("value: a number")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CalcError("value: a finite number")
        return Fraction(repr(value))
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d{1,60}(?:\.\d{1,60})?(?:[eE][+-]?\d{1,3})?\s*", value):
        return Fraction(value.strip())
    raise CalcError("value: a number")


# -- dates ----------------------------------------------------------------------------------------------------------------

def _date(value, what: str) -> dt.date:
    if isinstance(value, str) and value.strip().lower() == "today":
        return dt.date.today()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise CalcError(f"{what}: a date as YYYY-MM-DD (or 'today')")
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        raise CalcError(f"{what}: {value.strip()} is not a calendar date") from None


def _add_months(day: dt.date, months: int) -> tuple[dt.date, bool]:
    """DAY plus MONTHS; the day of month clamped to the month's last (True if it was)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    if not 1 <= year <= 9999:
        raise CalcError("the date would leave the years 1-9999")
    last = [31, 29 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31,
            30, 31][month]
    return dt.date(year, month + 1, min(day.day, last)), day.day > last


# -- tools ----------------------------------------------------------------------------------------------------------------

def _run(work):
    try:
        return work()
    except CalcError as exc:
        return {"error": str(exc)}


@mcp.tool()
def calculate(expression: str) -> dict:
    """Calculates an arithmetic expression exactly: + - * / // % and ** (or ^), parentheses, 15% as 0.15, constants
    pi, e, tau and functions sqrt, cbrt, exp, ln, log (log(x) natural, log(x, base)), log10, log2, sin, cos, tan,
    asin, acos, atan, atan2, sinh, cosh, tanh, degrees, radians, hypot, abs, floor, ceil, round, trunc, factorial,
    comb, perm, gcd, lcm, min, max, sum, mean. Decimal numbers are exact (0.1 + 0.2 = 0.3); 'exact' says whether the
    result is. Use it for every calculation instead of computing in your head."""
    return _run(lambda: evaluate(expression))


@mcp.tool()
def convert_units(value: float | str, from_unit: str, to_unit: str) -> dict:
    """Converts a value between units of the same kind: length (m, km, cm, mm, in, ft, yd, mi, nmi), area (m2, ha,
    acre, ft2), volume (l, ml, m3, gal, qt, cup, floz), mass (kg, g, mg, t, lb, oz), time (s, ms, min, h, d, week,
    year), speed (m/s, km/h, mph, kn), temperature (C, F, K), data (b, B, kB, MB, GB, KiB, MiB, GiB, Mbit), energy (J,
    kJ, cal, kcal, Wh, kWh), power (W, kW, hp), pressure (Pa, hPa, bar, atm, psi), angle (deg, rad)."""
    def work():
        amount = _number(value)
        source, target = _unit(from_unit), _unit(to_unit)
        if source[0] != target[0]:
            raise CalcError(f"{from_unit.strip()} is {source[0]}, {to_unit.strip()} is {target[0]}: not convertible")
        if source[0] == "temperature":
            kelvin = {"C": amount + Fraction("273.15"), "F": (amount - 32) * Fraction(5, 9) + Fraction("273.15"),
                      "K": amount}[source[1]]
            if kelvin < 0:
                raise CalcError("below absolute zero")
            result = {"C": kelvin - Fraction("273.15"), "F": (kelvin - Fraction("273.15")) * Fraction(9, 5) + 32,
                      "K": kelvin}[target[1]]
        else:
            result = amount * source[1] / target[1]
        text = _decimal(result, 20)
        if len(text) > 60:
            text = f"{float(result):.{FLOAT_DIGITS}g}"
        return {"value": _decimal(amount, 20), "from": from_unit.strip(), "to": to_unit.strip(), "result": text,
                "kind": source[0], "exact": source[0] != "angle" and not text.endswith("…")}
    return _run(work)


@mcp.tool()
def date_diff(start: str, end: str) -> dict:
    """The time between two dates (YYYY-MM-DD, or 'today'): days, weeks and days, and whole years, months and days;
    negative when end is before start. Also each date's weekday."""
    def work():
        first, second = _date(start, "start"), _date(end, "end")
        sign = 1 if second >= first else -1
        low, high = (first, second) if sign == 1 else (second, first)
        months = (high.year - low.year) * 12 + high.month - low.month
        anchor, _ = _add_months(low, months)
        if anchor > high:
            months -= 1
            anchor, _ = _add_months(low, months)
        days = (high - low).days
        return {"start": first.isoformat(), "start_weekday": first.strftime("%A"),
                "end": second.isoformat(), "end_weekday": second.strftime("%A"),
                "days": sign * days, "weeks_and_days": [sign * (days // 7), sign * (days % 7)],
                "years_months_days": [sign * (months // 12), sign * (months % 12), sign * (high - anchor).days],
                "business_days": sign * _business_days(low, high)}
    return _run(work)


def _business_days(low: dt.date, high: dt.date) -> int:
    """Monday-Friday days from LOW (included) to HIGH (excluded); no holidays."""
    days = (high - low).days
    whole, rest = divmod(days, 7)
    count = whole * 5
    for offset in range(rest):
        if (low.weekday() + offset) % 7 < 5:
            count += 1
    return count


@mcp.tool()
def date_add(date: str, days: int = 0, weeks: int = 0, months: int = 0, years: int = 0) -> dict:
    """A date (YYYY-MM-DD, or 'today') plus (or, with negative numbers, minus) years, months, weeks and days, in that
    order; the day of month is clamped to the month's end (Jan 31 + 1 month = Feb 28/29). Answers the date and its
    weekday."""
    def work():
        day = _date(date, "date")
        for name, amount, limit in (("days", days, 3_660_000), ("weeks", weeks, 522_000), ("months", months, 120_000),
                                    ("years", years, 10_000)):
            if isinstance(amount, bool) or not isinstance(amount, int) or abs(amount) > limit:
                raise CalcError(f"{name}: a whole number from -{limit} to {limit}")
        result, clamped = _add_months(day, years * 12 + months)
        try:
            result = result + dt.timedelta(days=days + 7 * weeks)
        except OverflowError:
            raise CalcError("the date would leave the years 1-9999") from None
        answer = {"date": day.isoformat(), "result": result.isoformat(), "weekday": result.strftime("%A")}
        if clamped:
            answer["note"] = "the day of month was clamped to the end of the month"
        return answer
    return _run(work)


def tools_only(server):
    """SERVER (a FastMCP) advertises tools only: FastMCP registers the handlers of resources and prompts for every
    server, and the capabilities of the initialize answer follow the handlers, so a server that publishes neither
    advertised both. Agents then offer a model tools for MCP resources (Hermes four more per server), which local
    models took for the way to the server's tools (sandbox-ai research round 1, "the MCP-resource trap")."""
    import mcp.types as types
    for request in (types.ListResourcesRequest, types.ReadResourceRequest, types.ListResourceTemplatesRequest,
                    types.ListPromptsRequest, types.GetPromptRequest):
        server._mcp_server.request_handlers.pop(request, None)


if __name__ == "__main__":
    sys.setrecursionlimit(2000)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    tools_only(mcp)
    mcp.run("stdio")
