# Signing the catalog

sandbox-ai's `mcp add` takes an entry only from a catalog with a valid signature:

```
sandbox-mcp: NAME: its catalog is not signed by a trusted key (https://raw.githubusercontent.com/c0decave/sandbox-ai-mcp/main/catalog.json.sig cannot be read) ... --unsigned adds it anyway
```

The signature (`ssh-keygen -Y sign`, namespace `sandbox-ai-mcp`, principal `mcp@sandbox-ai`) says that every
published server of the catalog was built from its pinned sources and passed its smoke tests with sandbox-ai
under Podman and under Bubblewrap, for exactly the image digest and rootfs hash the catalog pins.
sandbox-ai checks it against its file `sandbox/mcp-signers`.

## What sandbox-ai reads

For the catalog `https://raw.githubusercontent.com/c0decave/sandbox-ai-mcp/main/catalog.json`
(sandbox-ai's `sandbox/mcp.py`, `CATALOGS`) it fetches, from the top of branch `main`:

| file | what for |
|---|---|
| `catalog.json` | the entries, each image pinned by digest |
| `catalog.json.sig` | the signature over `catalog.json`; without it every entry is refused (unless `--unsigned`) |
| `rootfs.json` | the Bubblewrap form of each server: archive URL (a release asset), SHA-256, entrypoint, user |
| `rootfs.json.sig` | its signature; a signed catalog takes only a signed `rootfs.json` (otherwise Podman only) |

`scripts/sign_catalog.py` writes both `.sig` files next to their files at the top of the repository, which is
where raw.githubusercontent.com serves them from (`tests/test_sign_catalog.py` checks this with sandbox-ai's own
code when `SANDBOX_AI_CHECKOUT` names a sandbox-ai checkout).

## What the CI run produces

`.github/workflows/build.yml`, per server of `servers/`: build, smoke test with the hardened run line, Trivy,
push to `ghcr.io/c0decave/sandbox-ai-mcp-NAME`, then with a checkout of sandbox-ai (`SANDBOX_AI_REF`):

- `smoke-NAME-sandbox-ai-podman.json`: the pushed `IMAGE@DIGEST` started with sandbox-ai's own `podman run` line
  (`mcp.image_command`), `tools/list` compared with `servers/NAME/tools.json`, the smoke calls;
- `rootfs-NAME.tar.gz` and `rootfs-NAME.json` from that very image (`scripts/rootfs.py`);
- `smoke-NAME-sandbox-ai-bwrap.json`: the archive checked, unpacked and run with sandbox-ai's Bubblewrap runner
  (`mcp_rootfs`), with its `rootfs_sha256`;
- on `main`: the archive published as the release `rootfs-NAME-<first 12 hex digits of its SHA-256>`.

The `catalog` job (only for `main`) turns the digests and rootfs files into `catalog.json`, `rootfs.json` and
`digests.json` and uploads them with all smoke reports as the artifact `catalog`
(the reports in its folder `ci-digests/`).

`sign_catalog.py` refuses unless `catalog.json` and `rootfs.json` are what `servers/*/server.json` and
`digests.json` give (`make_catalog.py --check`) and every entry with a digest has both reports, passed, of the
right runner, with `tools.json` matched, for the pinned `IMAGE@DIGEST` and the `rootfs.json` SHA-256.

## Before the first run

- The smoke runs check out `github.com/c0decave/sandbox-ai` at `SANDBOX_AI_REF` (repository variable, default
  `main`). It must contain `sandbox/mcp_rootfs.py` and `sandbox/mcp-signers` (signed MCP catalogs and
  Bubblewrap servers); the job stops with an error naming the file otherwise. If the published `main` does not
  have them yet, publish sandbox-ai first or point the variable at a tag that has them:
  `gh variable set SANDBOX_AI_REF -R c0decave/sandbox-ai-mcp --body vX.Y.Z`.
- `sandbox/mcp-signers` of the published sandbox-ai must carry the line of the signing key's `.pub`, or users'
  sandbox-ai will not trust the signature.
- Optional: the repository secret `BRAVE_API_KEY` (without it brave-search's smoke runs only the refused call).

## The steps

Run them from the repository. `KEY` is the signing key (on the host `~/.config/sandbox-ai/mcp-signing-key`),
`SANDBOX_AI` a sandbox-ai checkout whose `sandbox/mcp-signers` has its public key.

```bash
KEY=~/.config/sandbox-ai/mcp-signing-key
SANDBOX_AI=../sandbox-ai
ME=(-c user.name=dash -c user.email=c0decave@users.noreply.github.com)

# 1. The public snapshot: branch "public" has the tree of main (none of main's local history).
#    If main moved, refresh it: before the first push one commit of its own (no parent), once
#    published a new commit on top of public (add  -p public  to commit-tree), so the push fast-forwards.
test "$(git rev-parse 'main^{tree}')" = "$(git rev-parse 'public^{tree}')" || {
  c=$(GIT_AUTHOR_NAME=dash GIT_AUTHOR_EMAIL=c0decave@users.noreply.github.com \
      GIT_COMMITTER_NAME=dash GIT_COMMITTER_EMAIL=c0decave@users.noreply.github.com \
      git commit-tree 'main^{tree}' -m "sandbox-ai-mcp: audited, container-packaged MCP servers for sandbox-ai")
  git branch -f public "$c"; }
git checkout public

# 2. Nothing private in it: 0 blocking (-r RULES_DIR if your privacy rules are not in
#    ~/.config/sandbox-ai/privacy).
sandbox-ai privacy-check -a .

# 3. The GitHub repository, and the snapshot as its main.
gh repo create c0decave/sandbox-ai-mcp --public \
  --description "Audited, container-packaged MCP servers for sandbox-ai, pinned by digest and signed"
git remote add github https://github.com/c0decave/sandbox-ai-mcp.git
git push github public:main

# 4. Wait for the build of main: it shows up a few seconds after the push
#    (if none started: gh workflow run build.yml -R c0decave/sandbox-ai-mcp --ref main).
RUN=$(gh run list -R c0decave/sandbox-ai-mcp --workflow build.yml --branch main -L 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN" -R c0decave/sandbox-ai-mcp --exit-status

# 5. Its catalog, rootfs.json, digests.json and the smoke reports.
CI=$(mktemp -d)
gh run download "$RUN" -R c0decave/sandbox-ai-mcp -n catalog -D "$CI"
cp "$CI/catalog.json" "$CI/rootfs.json" "$CI/digests.json" .

# 6. Sign (refuses unless every published server passed under Podman and Bubblewrap), then verify.
python3 scripts/sign_catalog.py --key "$KEY" --reports "$CI"
python3 scripts/sign_catalog.py --verify --signers "$SANDBOX_AI/sandbox/mcp-signers"

# 7. Commit and publish (this commit starts no rebuild: the workflow ignores these files).
git add catalog.json rootfs.json digests.json catalog.json.sig rootfs.json.sig
git "${ME[@]}" commit -m "Catalog of CI run $RUN, signed"
sandbox-ai privacy-check .
git push github public:main

# 8. The same commit on main (the local history), so main and public keep one tree.
git checkout main && git cherry-pick public && git push origin main
```

Then make the six packages `ghcr.io/c0decave/sandbox-ai-mcp-*` public if they are not
(github.com/c0decave?tab=packages, package settings, "Change visibility"): sandbox-ai pulls them without a login.

Check what users get:

```bash
curl -fsS https://raw.githubusercontent.com/c0decave/sandbox-ai-mcp/main/catalog.json.sig | head -1   # -----BEGIN SSH SIGNATURE-----
sandbox-ai mcp catalog          # the entries of "mcp" say "signed"
```

Every later release goes the same way: merge into main, refresh `public` (step 1, with `-p public`), push it
(a CI run of `main`), then steps 4 to 8 with that run's `catalog` artifact.
