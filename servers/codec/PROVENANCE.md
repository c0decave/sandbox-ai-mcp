# codec - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): a curated, offline set of CyberChef-style operations on Python's standard library; no third-party code beyond the shared lock |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's and servers/calculator's) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1` (no `ca-certificates`: no network) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Licences | `LICENSES/`: MCP Python SDK (MIT), sandbox-ai-mcp (MIT) |

## Why not CyberChef-MCP

The candidate of the 2026-11-25 list was doublegate/CyberChef-MCP (GPL-3.0-or-later; GitHub 37 stars, one maintainer):
npm `cyberchef-mcp` **4.2.0** (2026-09-12 05:34 UTC, 74 days old; tarball `cyberchef-mcp-4.2.0.tgz`, integrity
`sha512-7seNurQ1OnSFMHvhn1Dvl0zZvKZ4ShrJxVajs4QS4Ghvm77nH7JYovOA5DbTJcdt0FggeaMraEgsStjo90IsCA==`), looked at on
2026-11-25 from its registry metadata and release list. It stays out:

- **Not reviewable completely**: the package alone is 17.7 MB in 768 files (CyberChef's whole source, its web UI
  included) with **105 runtime dependencies**: among them tesseract.js (OCR that fetches its language data from a
  CDN at run time), jimp (images), kbpgp, node-forge, jsrsasign, libyara-wasm and libbzip2-wasm (WebAssembly),
  @alexaltea/capstone-js, d3, bootstrap, jquery, handlebars, the MCP TypeScript SDK v2, pino and piscina, and
  `@opentelemetry/api`.
- **An install script**: `postinstall: node scripts/patch-dependencies.mjs` (patches dependencies in place at
  install).
- **Telemetry code**: a `cyberchef_telemetry_export` tool (off by default, per its README) and the OpenTelemetry API.
- **Churn**: 3.9.0 to 4.2.0 within 30 hours (2026-09-10/12); every re-pin would need the same review again.
- **Too many tools for local models**: hundreds of operations as tools (its own "tool surface" benchmarks), where
  the catalog prefers a few tools with small schemas.

What agents need of CyberChef in this catalog's presets (forensics, mini-ctf, network-analysis, software-analysis) is
a few dozen operations: those are this own server, in about 600 lines of standard-library Python that can be read in
full.

## The server (`src/server.py`, read in full by its author; tests below)

- **Two tools.** `run_recipe` (a list of up to 20 operations, each an object with `op` and its arguments - extra
  arguments refused, not ignored - or just an operation's name) and `detect` (magic numbers of 21 formats, base64,
  base32, hex, binary, decimal codes, URL encoding, HTML entities, ascii85, a JWT, defanged indicators; each with
  the recipe that decodes it, a preview and what the preview looks like in turn).
- **Operations** (41): `from_`/`to_` base64 (standard and URL-safe, padding added), base32, base85, ascii85, hex
  (spaces, colons, `0x`, `\x` skipped), url, html_entities, binary, decimal, quoted_printable; `rot` (1-25);
  `xor` (key as hex, UTF-8 or base64, 1-4096 bytes, repeated); `reverse`; `gunzip` (several members) / `gzip`,
  `zlib_inflate` / `zlib_deflate`, `raw_inflate` / `raw_deflate`, `bunzip2` / `bzip2`, `unxz` / `xz`;
  `decode_text` / `encode_text` (a text charset of Python's codecs; binary-to-binary codecs such as rot13 or
  zlib_codec refused); `jwt_decode` (header and payload, the signature shown and **not** verified, said so); `hash`
  (md5, sha1, sha224, sha256, sha384, sha512, sha3_256, sha3_512, blake2b, blake2s, crc32, adler32); `strings`;
  `entropy`; `defang` / `refang`.
- **Bounds.** Input (text, hex, base64 or a file) at most 1 MiB; every step's result at most 16 MiB - decompressors
  run with a maximum length and stop there (a 47-byte bzip2 bomb of 17 MiB is refused), expanding encodings are
  refused before they are made when their result would pass the limit; 20 steps; 10 s per recipe (checked between
  steps; each step is bounded by size). Answers within 24,000 characters: text when the result is printable UTF-8,
  else a hex dump of the start, or base64 on request, with what was left out counted.
- **Files.** A `path` in `/work` only: walked one name at a time with `O_NOFOLLOW` from `/work`'s descriptor (no
  `..`, no link followed, also not inside `/work`), a regular file of at most 1 MiB; never written.
- **No network, no processes, no code from input**: no `eval`, `exec`, `pickle`, regular expressions from input or
  subprocesses; the standard library's `base64`, `binascii`, `quopri`, `html`, `urllib.parse`, `zlib`, `bz2`, `lzma`,
  `hashlib`, `codecs`.
- Tools only (no resources or prompts advertised); both tools annotated read-only.

## Tests

`tests/test_codec.py` (9 tests: 17 round trips and ROT/charset pairs, known values - MD5/SHA-256/CRC-32 test
vectors, XOR, URL-safe base64, defanging, strings, JWT -, a CTF recipe, detect on 16 kinds of input, the bounds -
gzip, zlib, bzip2 and xz bombs, an expansion, input size, 0 and 21 steps, the time limit -, 13 refused arguments, a
misspelt argument, the output formats, files in /work and 8 refused paths), `test_own_servers.py` `test_codec`
(inside the image in CI); smoke spec: 6 real calls (a recipe, detect, a hash, a JWT, detect and strings on the
fixtures `firmware.bin` and `hello`) + 2 refused (a path outside /work, a bzip2 bomb). Run on 2026-11-25 with the
shared lock in a Python 3.13 venv: 9 passed; the smoke spec over stdio 8/8.

## Risks left

- A recipe can take a few seconds on 16 MiB intermediate results (each step is bounded by size, the time is checked
  between steps); the container's CPU limit holds it.
- `detect` is a heuristic: it names what an input *may* be (a hex string is also valid base64); the previews show
  which reading makes sense.
- What an input decodes to is data, never instructions (said in the server's instructions).
