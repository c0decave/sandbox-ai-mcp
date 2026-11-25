# calculator - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-18); no third-party MCP code |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's); arithmetic with the standard library (`ast`, `fractions`, `math`, `datetime`) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` (unused: no network; kept so the layers equal the other servers') |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why our own

The research's candidate, githejie/mcp-server-calculator 0.2.1 (MIT, 67 lines), evaluates an AST with every `math`
function and `**` without any limit: `9**9**9` or `factorial(10**8)` hangs the server or exhausts its memory, a
denial of service any prompt injection can trigger. A bounded evaluator is short enough to write and review here,
and local models need more than arithmetic: exact decimals, units and dates are what they get wrong.

## This server

**Tools:** `calculate(expression)`, `convert_units(value, from_unit, to_unit)`, `date_diff(start, end)`,
`date_add(date, days, weeks, months, years)`.

**How `calculate` is safe:** the expression (1-1,000 characters; `^`, `×`, `÷`, `−`, `_` digit separators and `15%`
normalised) is parsed with `ast.parse(mode="eval")` and walked by an interpreter that knows only number literals,
`+ - * / // % **`, unary `+ -`, the constants `pi e tau` and 33 named functions called by plain name without keyword
arguments; anything else (names, attributes, subscripts, lists, strings, booleans, lambdas, comprehensions, calls of
anything else) is refused. Never `eval`, `exec` or `compile` to code. Bounds, checked before each operation is done:
at most 400 nodes; exact integers, numerators and denominators at most 1,000 digits (a power is refused when
`log10(base) * exponent` exceeds that); exact exponents at most 100,000; `factorial` 0-450; `comb`/`perm` n at most
10,000; `round` places -20 to 50; floating-point overflow, NaN and complex results refused; a deep nesting is refused by
the parser or the node limit; a 2-second deadline is checked at every node. Integers over 60 digits are shown rounded
with their digit count, the echoed expression at most 200 characters: every answer is short.

**Exactness:** number literals are exact fractions as written (`0.1` is 1/10), `+ - * / // %` and integer powers stay
exact, an exact square root stays exact (`sqrt(16/9)`), everything else (irrational functions, constants, fractional
powers) is IEEE floating point shown with 15 significant digits; `exact` in the answer says which. Repeating decimals
are shown to 30 places with `…` and the fraction.

**Units:** 12 kinds (length, area, volume, mass, time, speed, data, energy, power, pressure, angle; temperature with
offsets), exact factors as fractions from their definitions (inch 0.0254 m, pound 0.45359237 kg, US gallon
3.785411784 l, ...); a lower-case unit is accepted when it names one unit only. **Dates:** ISO dates (or `today`),
years 1-9999, months added with the day clamped to the month's end, business days without holidays.

**Network:** none. No mount, no secret, nothing read or written.

## Tested

Natively (`tests/test_calculator.py`, `tests/test_own_servers.py` `test_calculator`): handshake, tools equal to
`tools.json`, tools only; 19 exact results (0.1 + 0.2, 1/3, 200 * 15%, factorial(20), comb, gcd, lcm, round(2.675, 2)
= 2.68 as written, ...); floating-point functions; 22 errors (division by zero, domains, complex, unknown names and
functions, strings, booleans, lists, lambdas, attribute access, `__import__`, keywords); 17 hostile expressions
(`9**9**9`, `factorial(10**8)`, `10**1001`, `2**100000`, `comb(10**9, 5)`, 1,001 digits, 300 nested parentheses,
900 minus signs, 450 additions, a 990-digit denominator, `lcm` of 300 primes, ...) each answered in under 2.5 s and
under 600 characters; units (exact results, temperatures, absolute zero, incompatible kinds, unknown units); dates
(month ends, negative spans, business days, invalid dates, year 10000). The smoke spec: four real calls and two
refused.

## Verdict

Our own code, reviewed with this repository's tests; no dependency beyond the shared lock. **Pending**: fit to sign
once CI has built it and both smoke reports pass.
