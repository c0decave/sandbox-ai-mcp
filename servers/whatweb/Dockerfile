# Web site fingerprinting: WhatWeb 0.6.4 (urbanadventurer/WhatWeb, GPL-2.0-or-later) behind an MCP server of
# sandbox-ai-mcp (src/server.py), MCP over stdio. See PROVENANCE.md for the audit and the pins.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# The commit of the tag v0.6.4 (GitHub release of 2026-04-02).
ARG WHATWEB_COMMIT=d279d93042d034f3fd29d5a893d44ccc0595d3f8
RUN apt-get update \
 && apt-get install -y --no-install-recommends git=${GIT_VERSION} ca-certificates=20250419+deb13u1
RUN git init --quiet /src \
 && git -C /src fetch --quiet --depth 1 https://github.com/urbanadventurer/WhatWeb ${WHATWEB_COMMIT} \
 && git -C /src checkout --quiet FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "${WHATWEB_COMMIT}" \
 && test "$(sha256sum < /src/LICENSE)" = "8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643  -"
# Only what runs: the whatweb script, lib/ and plugins/ (1,832 plugins). Removed, not changed: the network
# loggers (MongoDB, Elasticsearch: never asked for, but loaded with lib/logging/*), the IP-to-country CSV (the
# Country plugin reads the shipped country-ips.dat and writes only when that is missing), plugins-disabled/ and
# the tutorial plugins of my-plugins/ (WhatWeb loads plugins/ and my-plugins/; the folder has to exist).
RUN mkdir -p /out/whatweb/my-plugins \
 && cp -a /src/whatweb /src/lib /src/plugins /src/LICENSE /out/whatweb/ \
 && rm /out/whatweb/lib/logging/mongodb.rb /out/whatweb/lib/logging/elasticsearch.rb /out/whatweb/plugins/IpToCountry.csv \
 && test "$(find /out/whatweb/plugins -maxdepth 1 -name '*.rb' | wc -l)" = 1832 \
 && test "$(find /out/whatweb/plugins -type f ! -name '*.rb' | sort | tr '\n' ' ')" = "/out/whatweb/plugins/country-codes.txt /out/whatweb/plugins/country-ips.dat " \
 && test -z "$(ls -A /out/whatweb/my-plugins)" && test ! -e /out/whatweb/plugins-disabled \
 && chmod -R a+rX,go-w /out/whatweb

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-whatweb" \
      org.opencontainers.image.description="Web site fingerprinting with WhatWeb, public addresses only, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND GPL-2.0-or-later"
# Ruby 3.3 from trixie-security; addressable and public_suffix (WhatWeb's only gem outside Ruby) from Debian. ipaddr,
# json, getoptlong, resolv-replace and open-uri are Ruby 3.3's default gems (libruby3.3). No optional gem (mongo,
# rchardet, pry) is installed, so WhatWeb loads none.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 ruby=1:3.3+b1 ruby3.3=3.3.13-0+deb13u1 libruby3.3=3.3.13-0+deb13u1 \
      ruby-rubygems=3.6.7-2 ruby-addressable=2.8.7-2 ruby-public-suffix=6.0.1-1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /out/whatweb /opt/whatweb
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-whatweb/
# WhatWeb starts and loads every plugin (1,831 names: two files define nopCommerce) without an error.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && cd /tmp \
 && /usr/bin/ruby3.3 -W0 /opt/whatweb/whatweb --version | grep -qxF 'WhatWeb version 0.6.4 ( https://morningstarsecurity.com/research/whatweb/ )' \
 && /usr/bin/ruby3.3 -W0 /opt/whatweb/whatweb --colour=never --list-plugins > /tmp/plugins.txt 2> /tmp/plugins.err \
 && grep -qxF 'Total: 1831 Plugins' /tmp/plugins.txt && ! grep -qi 'error' /tmp/plugins.err \
 && rm /tmp/plugins.txt /tmp/plugins.err
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
