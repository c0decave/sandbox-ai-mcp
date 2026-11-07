# Your own SearXNG instance, hardened

The `searxng` MCP server needs an instance that answers `format=json`; public instances
usually refuse it. Run your own with the official image, pinned by digest, as rootless Podman
with nothing it does not need. Not tested in this repository's CI (it runs the MCP server, not
the instance): check it on your host.

```bash
mkdir -p ~/.config/searxng && cd ~/.config/searxng
cat > settings.yml <<YAML
use_default_settings: true
server:
  secret_key: "$(openssl rand -hex 32)"
  limiter: false          # only you (and your sandboxes' MCP server) reach it
  image_proxy: false
search:
  formats: [html, json]
YAML
chmod 600 settings.yml

# Pin the image: pull once, read its digest, use only that from then on.
podman pull docker.io/searxng/searxng:latest
DIGEST=$(podman image inspect --format '{{.Digest}}' docker.io/searxng/searxng:latest)

podman run -d --name searxng --replace \
  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  --tmpfs /var/cache/searxng:rw,nosuid,nodev,size=128m \
  --cap-drop=ALL --cap-add=CHOWN --cap-add=SETGID --cap-add=SETUID \
  --security-opt=no-new-privileges --pids-limit=256 --memory=512m \
  -v ~/.config/searxng/settings.yml:/etc/searxng/settings.yml:ro \
  -p 127.0.0.1:8888:8080 \
  "docker.io/searxng/searxng@$DIGEST"
curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | head -c 200
```

The three capabilities are for the image's entrypoint, which switches to its own user; if
your image version starts without them, drop them. Then:

```bash
echo 'export SEARXNG_URL=http://HOST-IP:8888' >> ~/.bashrc && export SEARXNG_URL=http://HOST-IP:8888
sandbox-ai mcp add searxng --network full --env SEARXNG_URL   # taken from your environment at each start
sandbox-ai claude --mcp searxng
```

`HOST-IP` is an address of your machine that the MCP server's container reaches (not
127.0.0.1, which is the container itself); publish the port on that address instead of
127.0.0.1 then, or use an instance in your LAN.
