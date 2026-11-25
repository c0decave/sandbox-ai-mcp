#!/usr/bin/env python3
"""Write the recipes of the Qt toolchains from upstream's own metadata: every download pinned by its SHA-256.

    scripts/qt_recipe.py pyside6 VERSION [--line LINE] [--write]     Qt for Python, from PyPI
    scripts/qt_recipe.py qt VERSION [--line LINE] [--write]          the Qt SDK for C++, from download.qt.io

Without --write the recipe is printed; with it, it is toolchains/NAME/toolchain.json (--line 6.11: the older
version's toolchains/NAME/6.11/toolchain.json). `scripts/toolchain.py check` then holds it to the 14-day rule.

pyside6: the wheels shiboken6, PySide6_Essentials, PySide6_Addons (and PySide6_WebEngine, PySide6_Pdf where the
release has them) of VERSION for manylinux x86_64, each with the URL, SHA-256 and upload day PyPI's JSON API names
(https://pypi.org/pypi/NAME/VERSION/json), unpacked into python/ - a folder for Python's module path. They are The
Qt Company's own builds and carry Qt itself (libraries, plugins, QML modules, Designer, Linguist, Assistant, lupdate,
lrelease, qmllint, qmlformat, qmlls, uic, rcc). The license texts come from the tag of the release in its source
repository (github.com/pyside/pyside-setup, github.com/qt/qtbase): the wheels hold none.

qt: the 7z archives of the open-source Qt online repository for Linux x86_64 (desktop, gcc_64) - the packages the
Qt installer and aqtinstall install -, named by its Updates.xml: the base package, the add-on modules of ADDONS and
the extensions of EXTENSIONS, never debug information, sources, documentation or examples, never a package of
another licence (the open-source repository has none; a name outside the lists is left out and named). Each archive
is pinned by the SHA-256 download.qt.io publishes beside it (ARCHIVE.sha256). aqtinstall itself is not used: what
it adds to these two requests is py7zr and nine packages below it, which nobody here has read in full; the builder
reads 7z through bsdtar and writes every file itself. What the Qt installer does after unpacking is done as steps:
mkspecs/qconfig.pri is set to the open-source edition, bin/qt.conf and libexec/qt.conf name the prefix.

aarch64 is not offered: Qt's builds for it (the SDK's and the wheels') need glibc 2.38, sandbox-ai's images have
2.36, and a toolchain enters the catalog only when it ran under Podman too.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPI = "https://pypi.org/pypi"
RAW = "https://raw.githubusercontent.com"
QT_REPOSITORY = "https://download.qt.io/online/qtsdkrepository/linux_x64"
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
LIMIT = 64 << 20
# What Qt's libraries take from the system, measured on the wheels of 6.11.3 and 6.12.0 (scripts/toolchain.py
# build): QtCore, QtGui, QtWidgets, QtQml, QtQuick, QtNetwork, QtDBus and what is built on them. sandbox-ai's agent
# images have every one (sandbox-ai: toolchains.OWN_IMAGE).
LIBRARIES = ["libstdc++.so.6", "libgcc_s.so.1", "libz.so.1", "libzstd.so.1", "libglib-2.0.so.0",
             "libgthread-2.0.so.0", "libEGL.so.1", "libGL.so.1", "libX11.so.6", "libfontconfig.so.1",
             "libfreetype.so.6", "libxkbcommon.so.0", "libbrotlicommon.so.1", "libbrotlidec.so.1",
             "libgssapi_krb5.so.2", "libdbus-1.so.3"]
GLIBC = "2.34"
# The parts that need more than LIBRARIES, by what they are for: measured, noted, not checked at a start. Each is
# there and works where its libraries are (the xcb and Wayland platforms with --gui: the agent images have theirs).
OPTIONAL = [
    "*/platforms/libqxcb.so", "*/libQt6XcbQpa.so*", "*/xcbglintegrations/*",                  # X11 (--gui)
    "*/libQt6Wayland*", "*/libQt6Wl*", "*/platforms/libqwayland*", "*/wayland-*/*",           # Wayland
    "*/qml/QtWayland/*",
    "*/libQt6EglFS*", "*/libQt6EglFs*", "*/egldeviceintegrations/*", "*/platforms/libqlinuxfb.so",  # a framebuffer
    "*/libQt6WebEngine*", "*/libQt6Pdf*", "*/QtWebEngineProcess",                             # Chromium's libraries
    "*/libQt6Multimedia.so*", "*/plugins/multimedia/*", "*/libav*", "*/libsw*",               # PulseAudio, FFmpeg
    "*/libQt6FFmpegStub*", "*/libQt6SpatialAudio*", "*/libQt6Quick3DSpatialAudio*",
    "*/platformthemes/libqgtk3.so", "*/printsupport/*",                                       # GTK 3, CUPS
    "*/sqldrivers/libqsqloci.so", "*/sqldrivers/libqsqlibase.so", "*/sqldrivers/libqsqlmimer.so",
    "*/sqldrivers/libqsqlmysql.so", "*/sqldrivers/libqsqlodbc.so", "*/sqldrivers/libqsqlpsql.so",
    "*/libQt6Nfc.so*", "*/texttospeech/*", "*/networkinformation/libqglib.so",
    "*/libQt6Quick3DXr*",
]
LICENSES = (  # (repository, file of its LICENSES folder, what it is the license of)
    ("pyside/pyside-setup", "LGPL-3.0-only.txt", "Qt and Qt for Python (with GPL-2.0-only and GPL-3.0-only)"),
    ("pyside/pyside-setup", "GPL-3.0-only.txt", "Qt's GPL-only modules; an alternative for the others"),
    ("pyside/pyside-setup", "GPL-2.0-only.txt", "an alternative for the LGPL modules"),
    ("pyside/pyside-setup", "Qt-GPL-exception-1.0.txt", "Qt's tools (GPL-3.0-only with this exception)"),
    ("qt/qtbase", "LGPL-2.1-or-later.txt", "FFmpeg, inside Qt Multimedia"),
    ("qt/qtbase", "BSD-3-Clause.txt", "third-party code inside Qt (see NOTICE.txt)"),
    ("qt/qtbase", "MIT.txt", "third-party code inside Qt (see NOTICE.txt)"),
)
# PySide6's console scripts (PySide6/scripts/pyside_tool.py), as commands.
PYSIDE_TOOLS = ("uic", "rcc", "designer", "linguist", "assistant", "lupdate", "lrelease", "qml", "qmllint",
                "qmlformat", "qmlls", "qmlcachegen", "qmltyperegistrar", "qmlimportscanner", "project", "genpyi",
                "metaobjectdump", "deploy", "qsb", "balsam", "svgtoqml")
# The Qt SDK: the add-on modules and extensions taken (all that make sense on a Linux desktop), and why others not.
ADDONS = ("qt3d", "qt5compat", "qtcharts", "qtconnectivity", "qtdatavis3d", "qtgraphs", "qtgrpc", "qthttpserver",
          "qtimageformats", "qtlanguageserver", "qtlocation", "qtlottie", "qtmultimedia", "qtnetworkauth",
          "qtpositioning", "qtquick3d", "qtquick3dphysics", "qtquickeffectmaker", "qtquicktimeline",
          "qtremoteobjects", "qtscxml", "qtsensors", "qtserialbus", "qtserialport", "qtshadertools", "qtspeech",
          "qtvirtualkeyboard", "qtwebchannel", "qtwebsockets", "qtwebview")
EXTENSIONS = ("qtwebengine", "qtpdf")
SDK_COMMANDS = {
    "qmake": "bin/qmake", "qmake6": "bin/qmake6", "qt-cmake": "bin/qt-cmake", "qtpaths": "bin/qtpaths",
    "moc": "libexec/moc", "uic": "libexec/uic", "rcc": "libexec/rcc", "lupdate": "bin/lupdate",
    "lrelease": "bin/lrelease", "lconvert": "bin/lconvert", "designer": "bin/designer", "linguist": "bin/linguist",
    "assistant": "bin/assistant", "qml": "bin/qml", "qmllint": "bin/qmllint", "qmlformat": "bin/qmlformat",
    "qmlls": "bin/qmlls", "qmlcachegen": "libexec/qmlcachegen", "qmltyperegistrar": "libexec/qmltyperegistrar",
    "qmlimportscanner": "libexec/qmlimportscanner", "qsb": "bin/qsb", "balsam": "bin/balsam",
}


class Refused(ValueError):
    pass


def fetched(url: str, opener=None, limit: int = LIMIT) -> bytes:
    if not url.startswith("https://"):
        raise Refused(f"{url}: not https")
    opener = opener or (lambda u: urllib.request.urlopen(u, timeout=120))  # noqa: S310 - https only (checked)
    try:
        with opener(url) as source:
            data = source.read(limit + 1)
    except OSError as exc:
        raise Refused(f"{url}: {getattr(exc, 'reason', None) or exc}") from None
    if len(data) > limit:
        raise Refused(f"{url}: larger than {limit >> 20} MiB")
    return data


def license_steps(tag: str, opener=None) -> list[dict]:
    """The license texts of the release TAG (v6.12.0), each fetched now, pinned by its SHA-256 and copied to
    licenses/."""
    steps = []
    for repository, name, _ in LICENSES:
        url = f"{RAW}/{repository}/{tag}/LICENSES/{name}"
        steps += [{"fetch": f"license-{name}", "url": url, "sha256": hashlib.sha256(fetched(url, opener)).hexdigest()},
                  {"copy": f"license-{name}", "to": f"licenses/{name}"}]
    return steps


def notice(what: str, version: str, sources: list[str]) -> str:
    lines = [f"{what} {version}, as published by The Qt Company, unchanged.", "",
             "Licenses: Qt and Qt for Python are available under LGPL-3.0-only, GPL-2.0-only or GPL-3.0-only; some",
             "modules only under GPL-3.0-only (Qt Charts, Qt Data Visualization, Qt Graphs, Qt HTTP Server, Qt Lottie,",
             "Qt Network Authorization, Qt Quick 3D, Qt Quick 3D Physics, Qt Quick Timeline, Qt Virtual Keyboard, Qt",
             "Wayland Compositor and others: https://doc.qt.io/qt-6/qtmodules.html names the license of each). Qt's",
             "tools are GPL-3.0-only with the Qt GPL exception 1.0. No module of the commercial-only editions is here.",
             "The texts: licenses/ in this folder.", "",
             "Third-party code inside Qt (FFmpeg under LGPL-2.1-or-later, Chromium in Qt WebEngine, ICU, HarfBuzz,",
             "PCRE2, libpng, libjpeg, SQLite, zlib and others) with its licenses and copyright notices:",
             "https://doc.qt.io/qt-6/licenses-used-in-qt.html, and qt_attribution.json beside each in Qt's sources.",
             "", "The source code of exactly these binaries (LGPL-3.0 section 4, GPL-3.0 section 6):"]
    return "\n".join([*lines, *(f"  {url}" for url in sources), ""])


# --- pyside6: PyPI ---------------------------------------------------------------------------------------------


def wheel(package: str, version: str, opener=None) -> dict:
    """{"url", "sha256", "released"} of PACKAGE VERSION's wheel for manylinux x86_64, as PyPI names it."""
    document = json.loads(fetched(f"{PYPI}/{package}/{version}/json", opener))
    found = [item for item in document.get("urls", []) if item.get("packagetype") == "bdist_wheel"
             and re.search(r"-manylinux_[0-9_]+_x86_64\.whl$", item.get("filename", "")) and not item.get("yanked")]
    if len(found) != 1:
        raise Refused(f"{package} {version}: PyPI has {len(found)} wheels for manylinux x86_64, not one")
    item = found[0]
    if not item["url"].startswith("https://files.pythonhosted.org/packages/") or \
            not re.fullmatch(r"[0-9a-f]{64}", item["digests"]["sha256"]):
        raise Refused(f"{package} {version}: PyPI names {item['url']} without a SHA-256, or outside its file host")
    floor = re.search(r"-manylinux_([0-9]+)_([0-9]+)_x86_64\.whl$", item["filename"])
    return {"url": item["url"], "sha256": item["digests"]["sha256"], "released": item["upload_time"][:10],
            "glibc": f"{floor[1]}.{floor[2]}", "requires": document["info"].get("requires_dist") or [],
            "python": document["info"].get("requires_python") or ""}


def pinned(requirements: list[str], package: str):
    """The version REQUIREMENTS pin PACKAGE to (PACKAGE==VERSION without a marker), or None."""
    for requirement in requirements:
        match = re.fullmatch(rf"{re.escape(package)}==([0-9][0-9A-Za-z.]*)", requirement.replace(" ", ""), re.I)
        if match:
            return match[1]
    return None


def pyside6(version: str, opener=None) -> dict:
    if not VERSION.fullmatch(version):
        raise Refused(f"{version!r}: a release such as 6.12.0")
    meta = wheel("PySide6", version, opener)
    packages = [("shiboken6", version), ("PySide6_Essentials", version), ("PySide6_Addons", version)]
    for extra in ("PySide6_WebEngine", "PySide6_Pdf"):  # wheels of their own since 6.12 (in Addons before)
        at = pinned(meta["requires"], extra)
        if at:
            packages.append((extra, at))
    for package, at in packages[1:3]:
        if pinned(meta["requires"], package) != at:
            raise Refused(f"PySide6 {version} does not pin {package} to {at}: {meta['requires']}")
    packages.append(("PySide6", version))  # (its metadata alone: what importlib.metadata and pip show)
    steps, floors = [], set()
    for package, at in packages:
        found = meta if package == "PySide6" else wheel(package, at, opener)
        floors.add(found["glibc"])
        name = f"{package.lower()}.whl"
        steps += [{"fetch": name, "url": found["url"], "sha256": found["sha256"], "released": found["released"]},
                  {"unpack": name, "to": "python"}]
    if floors != {GLIBC}:
        raise Refused(f"the wheels of {version} are built for glibc {sorted(floors)}, the recipe says {GLIBC}: "
                      "measure again (LIBRARIES, GLIBC, OPTIONAL)")
    tool = ("#!/bin/sh\n# sandbox-ai-mcp toolchain pyside6: PySide6's own commands (its console scripts "
            "pyside6-uic, pyside6-rcc ...),\n# run with the python3 on PATH.\n"
            "tool=$(basename \"$0\"); tool=${tool#pyside6-}\n"
            "PYTHONPATH=\"{prefix}/python${PYTHONPATH:+:$PYTHONPATH}\" exec python3 -c 'import sys\n"
            "from PySide6.scripts import pyside_tool\nname = sys.argv.pop(1)\nsys.argv[0] = \"pyside6-\" + name\n"
            "sys.exit(getattr(pyside_tool, name.replace(\"-\", \"_\"))())' \"$tool\" \"$@\"\n")
    steps += [{"write": "bin/pyside6-tool", "mode": "755", "text": tool},
              *({"link": f"bin/pyside6-{name}", "to": "pyside6-tool"} for name in PYSIDE_TOOLS)]
    sources = [f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/"
               f"pyside-setup-everywhere-src-{version}.tar.xz",
               f"https://download.qt.io/official_releases/qt/{version.rsplit('.', 1)[0]}/{version}/single/"
               f"qt-everywhere-src-{version}.tar.xz",
               f"https://github.com/pyside/pyside-setup/tree/v{version}", f"https://github.com/qt/qt5/tree/v{version}"]
    steps += [*license_steps(f"v{version}", opener),
              {"write": "NOTICE.txt", "text": notice("Qt for Python (PySide6, Shiboken6) with Qt", version, sources)}]
    python = meta["python"]
    return {
        "name": "pyside6", "version": version,
        "title": "Qt for Python (PySide6)",
        "description": f"PySide6 {version} with Qt {version} itself: every module of the open-source edition (Core, "
                       "Gui, Widgets, Qml, Quick, Quick Controls, Network, Sql with SQLite, Svg, WebSockets, Charts, "
                       "Graphs, 3D, Quick 3D, Multimedia, WebEngine, Pdf ...), the platforms offscreen, xcb and "
                       "wayland, Designer, Linguist, Assistant, lupdate, lrelease, qmllint, qmlformat, qmlls and "
                       "pyside6-uic, pyside6-rcc. `import PySide6` works in the python3 on PATH "
                       f"(Python {python.replace(',', ', ')}: the toolchain python, attached with it) and in a "
                       "virtual environment; without a display Qt draws offscreen (QT_QPA_PLATFORM). The license "
                       f"texts and the sources of these binaries: licenses/ and NOTICE.txt in the tree ({sources[0]}, "
                       f"{sources[1]}).",
        "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
        "homepage": "https://doc.qt.io/qtforpython-6/",
        "arches": ["x86_64"],
        # (only PySide6's own names: designer, lupdate ... without the prefix are the Qt SDK's, the toolchain qt)
        "commands": {f"pyside6-{name}": f"bin/pyside6-{name}" for name in PYSIDE_TOOLS},
        "env": {"PYTHONPATH": "{prefix}/python", "QT_QPA_PLATFORM": "offscreen"},
        # (no registry of its own: nothing here installs; the toolchain python opens PyPI unless mounted offline)
        "caches": {}, "hosts": [], "allow": [],
        "needs": {"glibc": GLIBC, "libraries": LIBRARIES},
        "requires": ["python"],
        "optional": OPTIONAL,
        "build": steps,
        "smoke": PYSIDE_SMOKE,
        "notes": "The Qt Company's wheels from PyPI (URL, SHA-256 and upload day from PyPI's JSON API; written by "
                 "scripts/qt_recipe.py pyside6 VERSION). x86_64 only: the aarch64 wheels need glibc 2.38, sandbox-ai's "
                 "images have 2.36. The wheels hold no license text: licenses/ is from the release's tag in "
                 "pyside-setup and qtbase, NOTICE.txt names the sources. Not checked at a start, because not every "
                 "sandbox needs them (optional): the xcb and Wayland platforms (--gui; the agent images have their "
                 "libraries), Multimedia (libpulse), WebEngine (Chromium's libraries, in the agent images; as root it "
                 "wants QTWEBENGINE_DISABLE_SANDBOX=1), the GTK theme, CUPS, the SQL drivers other than SQLite.",
    }


WIDGET_QML = ("import QtQuick\nimport QtQuick.Controls\n\nRectangle {\n    width: 160; height: 120; color: \"#2060c0\"\n"
              "    Button { text: qsTr(\"hello from QML\"); anchors.centerIn: parent }\n}\n")
PYSIDE_APP = '''import sys
from PySide6.QtCore import QTimer, QUrl, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
label = QLabel("hello from PySide6")
label.resize(200, 60)
label.show()
view = QQuickView()
view.setSource(QUrl.fromLocalFile("hello.qml"))
view.show()


def colours(image):
    return {image.pixelColor(x, y).name() for x in range(0, image.width(), 4) for y in range(0, image.height(), 4)}


def done():
    widget, quick = label.grab().toImage(), view.grabWindow()
    widget.save("widget.png")
    quick.save("quick.png")
    print("pyside6", qVersion(), QGuiApplication.platformName(), "widget", len(colours(widget)) > 1, "quick",
          "#2060c0" in colours(quick) and len(colours(quick)) > 1)
    app.quit()


QTimer.singleShot(500, done)
sys.exit(app.exec())
'''
UI_FILE = ('<?xml version="1.0" encoding="UTF-8"?>\n<ui version="4.0">\n <class>Form</class>\n'
           ' <widget class="QWidget" name="Form">\n  <widget class="QPushButton" name="button">\n'
           '   <property name="text"><string>hello</string></property>\n  </widget>\n </widget>\n</ui>\n')
PYSIDE_SMOKE = [
    {"files": {"app.py": PYSIDE_APP, "hello.qml": WIDGET_QML},
     "run": "python3 app.py && test -s widget.png && test -s quick.png",
     "expect": "offscreen widget True quick True"},
    {"run": "python3 -c 'from PySide6 import QtCore, QtNetwork, QtSql, QtSvg, QtWebSockets, QtCharts, QtGraphs, "
            "Qt3DCore, QtQuick3D, QtQuickControls2, QtOpenGLWidgets, QtPrintSupport, QtTest, QtUiTools, QtDesigner, "
            "QtHelp, QtStateMachine, QtWebChannel, QtHttpServer, QtPdf\napp = QtCore.QCoreApplication([])\n"
            "db = QtSql.QSqlDatabase.addDatabase(\"QSQLITE\")\ndb.setDatabaseName(\":memory:\")\n"
            "print(\"modules\", QtCore.qVersion(), \"sqlite\", db.open())'",
     "expect": "sqlite True"},
    {"files": {"form.ui": UI_FILE, "res.qrc": "<RCC><qresource><file>hello.qml</file></qresource></RCC>\n"},
     "run": "pyside6-uic form.ui -o ui_form.py && pyside6-rcc res.qrc -o res_rc.py && python3 -c 'import res_rc, "
            "ui_form\nfrom PySide6.QtCore import QFile\nprint(ui_form.Ui_Form.__name__, QFile.exists(\":/hello.qml\"))'",
     "expect": "Ui_Form True"},
    {"run": "pyside6-qmllint hello.qml && pyside6-qmlformat hello.qml | head -n 1 && pyside6-lupdate hello.qml -ts "
            "hello_de.ts >/dev/null && pyside6-lrelease hello_de.ts -qm hello_de.qm >/dev/null && test -s hello_de.qm "
            "&& echo translated",
     "expect": "translated"},
    {"run": "python3 -m venv venv && venv/bin/python -c 'import PySide6.QtWidgets, sys\nprint(\"venv\", "
            "sys.prefix != sys.base_prefix, PySide6.__version__)'",
     "expect": "venv True"},
]


# --- qt: the online repository of download.qt.io -----------------------------------------------------------------


def digits(version: str) -> str:
    return version.replace(".", "")


def packages_of(xml_text: bytes, where: str) -> list[dict]:
    """[{"name", "version", "released", "archives": [names]}] of an Updates.xml."""
    try:
        root = xml.etree.ElementTree.fromstring(xml_text)
    except xml.etree.ElementTree.ParseError as exc:
        raise Refused(f"{where}: not XML ({exc})") from None
    found = []
    for update in root.iter("PackageUpdate"):
        name, version = (update.findtext("Name") or "").strip(), (update.findtext("Version") or "").strip()
        archives = [part.strip() for part in (update.findtext("DownloadableArchives") or "").split(",") if part.strip()]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", name) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,100}", version) \
                or not all(re.fullmatch(r"[A-Za-z0-9._+-]{1,200}\.7z", archive) for archive in archives):
            raise Refused(f"{where}: a package with a name, version or archive that is no plain name ({name!r})")
        found.append({"name": name, "version": version, "archives": archives,
                      "released": (update.findtext("ReleaseDate") or "").strip()})
    if not found:
        raise Refused(f"{where}: it names no package")
    return found


def archive_hash(url: str, opener=None) -> str:
    """The SHA-256 download.qt.io publishes beside an archive (URL.sha256: the hash, then the file's name)."""
    text = fetched(url + ".sha256", opener, 4096).decode("ascii", "replace").split()
    if not text or not re.fullmatch(r"[0-9a-f]{64}", text[0]):
        raise Refused(f"{url}.sha256: no SHA-256")
    return text[0]


def sdk_steps(version: str, opener=None, base: str = QT_REPOSITORY, out=print) -> list[dict]:
    """The fetch and unpack steps of the Qt SDK VERSION: the desktop package for gcc_64, ADDONS and EXTENSIONS."""
    number, steps, taken = digits(version), [], set()
    folders = [(f"{base}/desktop/qt6_{number}/qt6_{number}", None),
               *((f"{base}/extensions/{name}/{number}/x86_64", name) for name in EXTENSIONS)]
    for folder, extension in folders:
        try:
            listing = fetched(f"{folder}/Updates.xml", opener)
        except Refused as exc:
            if not extension:
                raise
            out(f"left out: the extension {extension} ({exc})")  # (said, never silently: Qt WebEngine, Qt PDF)
            continue
        for package in packages_of(listing, f"{folder}/Updates.xml"):
            name = package["name"]
            parts = name.split(".")
            if not name.endswith("gcc_64") or not package["archives"] or "debug" in name or \
                    any(part in parts for part in ("src", "doc", "examples")):
                continue
            # qt.qt6.6120.linux_gcc_64 (the base), qt.qt6.6120.addons.qtcharts.linux_gcc_64 (an add-on; older
            # releases name some without "addons"), extensions.qtwebengine.6120.linux_gcc_64
            middle = [part for part in parts[parts.index(number) + 1:-1] if part != "addons"] \
                if number in parts else ["?"]
            module = extension or (middle[-1] if middle else "qt")
            if not extension and middle and module not in ADDONS:
                out(f"left out: {name} (not among ADDONS)")
                continue
            if not package["version"].startswith(version + "-"):
                raise Refused(f"{folder}: {name} is {package['version']}, not {version}")
            try:
                released = datetime.date.fromisoformat(package["released"]).isoformat()
            except ValueError:
                raise Refused(f"{folder}: {name} has no release date ({package['released']!r})") from None
            for archive in package["archives"]:
                url = f"{folder}/{name}/{package['version']}{archive}"
                file = f"{module}-{archive}"
                steps += [{"fetch": file, "url": url, "sha256": archive_hash(url, opener), "released": released},
                          {"unpack": file, "strip": 2}]  # VERSION/gcc_64/... -> the prefix
            taken.add(module)
    missing = sorted({"qt", *ADDONS, *EXTENSIONS} - taken)
    if "qt" in missing:
        raise Refused(f"{base}: no desktop package for gcc_64 of Qt {version}")
    for module in missing:
        out(f"not in the repository for {version}: {module}")
    return steps


def qt(version: str, opener=None, base: str = QT_REPOSITORY, out=print) -> dict:
    if not VERSION.fullmatch(version):
        raise Refused(f"{version!r}: a release such as 6.12.0")
    steps = sdk_steps(version, opener, base, out)
    sources = [f"https://download.qt.io/official_releases/qt/{version.rsplit('.', 1)[0]}/{version}/single/"
               f"qt-everywhere-src-{version}.tar.xz", f"https://github.com/qt/qt5/tree/v{version}"]
    steps += [
        # What the Qt installer does after unpacking (its LineReplace operations; aqtinstall's Updater): the
        # packages are built once for every edition.
        {"replace": "mkspecs/qconfig.pri", "line": "QT_EDITION =", "with": "QT_EDITION = OpenSource"},
        {"replace": "mkspecs/qconfig.pri", "line": "QT_LICHECK =", "with": "QT_LICHECK ="},
        {"write": "bin/qt.conf", "text": "[Paths]\nPrefix=..\n"},
        {"write": "libexec/qt.conf", "text": "[Paths]\nPrefix=..\n"},
        *license_steps(f"v{version}", opener),
        {"write": "NOTICE.txt", "text": notice("The Qt SDK for Linux (gcc_64)", version, sources)},
    ]
    return {
        "name": "qt", "version": version,
        "title": "Qt for C++ (the Qt SDK)",
        "description": f"Qt {version} for C++ with CMake and qmake: headers, libraries, CMake packages, mkspecs, "
                       "plugins, QML modules and the tools (moc, uic, rcc, qmake, qt-cmake, lupdate, lrelease, "
                       "Designer, Linguist, Assistant, qmllint, qmlformat, qmlls) of the open-source edition: Core, "
                       "Gui, Widgets, Qml, Quick, Quick Controls, Network, Sql with SQLite, Svg, WebSockets, Charts, "
                       "Graphs, 3D, Quick 3D, Multimedia, WebEngine, Pdf and the other add-ons. It is built with GCC: "
                       "compile with GCC and libstdc++ (the image variant gcc, or the host's under Bubblewrap), not "
                       "with the toolchain cc, whose libc++ cannot link Qt. Qt for Python (pyside6) is attached with "
                       "it. Without a display Qt draws offscreen (QT_QPA_PLATFORM). The license texts and the "
                       f"sources of these binaries: licenses/ and NOTICE.txt in the tree ({sources[0]}).",
        "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
        "homepage": "https://doc.qt.io/qt-6/",
        "arches": ["x86_64"],
        "commands": dict(SDK_COMMANDS),
        "env": {"CMAKE_PREFIX_PATH": "{prefix}", "Qt6_DIR": "{prefix}/lib/cmake/Qt6", "QT_QPA_PLATFORM": "offscreen"},
        "caches": {}, "hosts": [], "allow": [],
        "needs": {"glibc": GLIBC, "libraries": LIBRARIES},
        "requires": ["pyside6"],
        "optional": OPTIONAL,
        "build": steps,
        "smoke": QT_SMOKE,
        "smoke_apt": ["g++", "make", "cmake", "ninja-build", "libgl1-mesa-dev"],
        "notes": "The open-source Qt online repository of download.qt.io (desktop, gcc_64): its Updates.xml names the "
                 "archives, ARCHIVE.sha256 beside each pins it (written by scripts/qt_recipe.py qt VERSION). "
                 "x86_64 only: the aarch64 builds need glibc 2.38. QT_PLUGIN_PATH and QML_IMPORT_PATH are not set: "
                 "Qt finds its own plugins and QML modules from where its libraries are, and the variables would "
                 "send every other Qt of the sandbox (PySide6's, a project's own) to this one's.",
    }


CPP_MAIN = '''#include <QApplication>
#include <QImage>
#include <QLabel>
#include <QQuickView>
#include <QSet>
#include <QSqlDatabase>
#include <QTimer>
#include <QUrl>
#include <chrono>
#include <cstdio>

using namespace std::chrono_literals;

static int colours(const QImage &image)
{
    QSet<QRgb> seen;
    for (int x = 0; x < image.width(); x += 4)
        for (int y = 0; y < image.height(); y += 4)
            seen.insert(image.pixel(x, y));
    return seen.size();
}

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QLabel label(QObject::tr("hello from Qt"));
    label.resize(200, 60);
    label.show();
    QQuickView view;
    view.setSource(QUrl::fromLocalFile(QStringLiteral("hello.qml")));
    view.show();
    QSqlDatabase db = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"));
    db.setDatabaseName(QStringLiteral(":memory:"));
    // (a std::chrono argument: only a C++ library of the ABI Qt was built with links this)
    QTimer::singleShot(500ms, &app, [&] {
        const QImage widget = label.grab().toImage(), quick = view.grabWindow();
        widget.save(QStringLiteral("widget.png"));
        std::printf("qt %s %s widget %d quick %d sqlite %d\\n", qVersion(), qPrintable(app.platformName()),
                    colours(widget) > 1, colours(quick) > 1, db.open());
        app.quit();
    });
    return app.exec();
}
'''
CMAKE_LISTS = '''cmake_minimum_required(VERSION 3.22)
project(hello LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Qt6 REQUIRED COMPONENTS Widgets Quick QuickControls2 Sql Svg Network WebSockets Charts)
qt_standard_project_setup()
qt_add_executable(hello main.cpp)
target_link_libraries(hello PRIVATE Qt6::Widgets Qt6::Quick Qt6::Sql)
'''
QMAKE_PRO = "QT += widgets quick sql\nCONFIG += c++17\nSOURCES += main.cpp\nTARGET = hello_qmake\n"
QT_SMOKE = [
    {"files": {"main.cpp": CPP_MAIN, "hello.qml": WIDGET_QML, "CMakeLists.txt": CMAKE_LISTS},
     "run": "cmake -S . -B build -G Ninja >cmake.log 2>&1 && cmake --build build >>cmake.log 2>&1 || "
            "{ tail -n 40 cmake.log; exit 1; }; ./build/hello && test -s widget.png",
     "expect": "offscreen widget 1 quick 1 sqlite 1"},
    {"files": {"hello.pro": QMAKE_PRO},
     "run": "mkdir -p qm && cd qm && qmake ../hello.pro >../qmake.log 2>&1 && make -j2 >>../qmake.log 2>&1 || "
            "{ tail -n 40 ../qmake.log; exit 1; }; cd .. && ./qm/hello_qmake",
     "expect": "offscreen widget 1 quick 1 sqlite 1"},
    {"files": {"form.ui": UI_FILE},
     "run": "uic form.ui -o ui_form.h && grep -c Ui_Form ui_form.h >/dev/null && moc --version && qmllint hello.qml "
            "&& lupdate main.cpp -ts hello_de.ts >/dev/null && lrelease hello_de.ts -qm hello_de.qm >/dev/null && "
            "test -s hello_de.qm && qtpaths --qt-version",
     "expect": "moc 6."},
]


def written(recipe: dict, line: str | None, root: Path = ROOT) -> Path:
    folder = root / "toolchains" / recipe["name"]
    path = (folder / line if line else folder) / "toolchain.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", choices=("pyside6", "qt"))
    parser.add_argument("version")
    parser.add_argument("--line", help="an older version's line (6.11): toolchains/NAME/LINE/toolchain.json")
    parser.add_argument("--write", action="store_true", help="write the recipe instead of printing it")
    parser.add_argument("--root", type=Path, default=ROOT)
    opts = parser.parse_args(argv)
    try:
        if opts.line and not (opts.version == opts.line or opts.version.startswith(opts.line + ".")):
            raise Refused(f"{opts.version} is not of the line {opts.line}")
        recipe = pyside6(opts.version) if opts.name == "pyside6" else \
            qt(opts.version, out=lambda line: print(line, file=sys.stderr))
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if opts.write:
        print(written(recipe, opts.line, opts.root))
    else:
        print(json.dumps(recipe, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
