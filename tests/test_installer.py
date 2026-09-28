"""setup.sh — fresh install, the v9.2.x → v9.3 state move, snapshots, rollback.

These run the real installer, as "root" inside a user namespace (`unshare -r`:
root inside, the calling user outside), against scratch directories, with
apt-get, systemctl, useradd, sleep and pip stubbed. Nothing on the host is
touched: every path is overridden, and fake root cannot write system files.
Skipped where unprivileged user namespaces or rsync are unavailable.
"""
import hashlib, json, os, shutil, subprocess, sys, tarfile, time
from types import SimpleNamespace
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(REPO, "setup.sh")
LEGACY_TAG = "v9.2.1"
STATE_FILES = ["users.json", "users.json.bak", "secret_key.txt", "cert.pem", "key.pem",
               "state.json", "network_config.json", "labels.json", "config.json"]


def _userns_ok():
    try:
        return subprocess.run(["unshare", "-r", "true"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not (_userns_ok() and shutil.which("rsync")),
                                reason="needs `unshare -r` and rsync")


def _exe(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


@pytest.fixture
def box(tmp_path):
    stubs = tmp_path / "stubs"; stubs.mkdir()
    log = tmp_path / "stub.log"
    _exe(stubs / "apt-get", "exit 0")
    _exe(stubs / "systemctl", 'echo "systemctl $*" >> "$STUB_LOG"; exit 0')
    _exe(stubs / "sleep", "exit 0")
    # The service user in these tests is root, which exists — so this must
    # never run. If it does, the test fails loudly.
    _exe(stubs / "useradd", 'echo "useradd $*" >> "$STUB_LOG"; exit 1')

    install = tmp_path / "opt" / "tc_lab"
    # A ready venv, so setup.sh neither creates one nor downloads anything:
    # pip is a no-op, python is the interpreter running these tests.
    (install / "venv" / "bin").mkdir(parents=True)
    _exe(install / "venv" / "bin" / "pip", "exit 0")
    _exe(install / "venv" / "bin" / "python", f'exec "{sys.executable}" "$@"')

    b = SimpleNamespace(
        root=tmp_path, install=install, state=tmp_path / "var" / "lib" / "tc_lab",
        units=tmp_path / "units", backups=tmp_path / "backups", log=log)
    b.env = {**os.environ,
             "PATH": f"{stubs}:{os.environ['PATH']}",
             "TC_LAB_DIR": str(install), "TC_LAB_STATE_DIR": str(b.state),
             "TC_LAB_UNIT_DIR": str(b.units), "TC_LAB_BACKUP_DIR": str(b.backups),
             "TC_LAB_BIN_DIR": str(tmp_path / "bin"), "TC_LAB_SERVICE": "tc_lab_test",
             "TC_LAB_USER": "root", "STUB_LOG": str(log)}
    b.unit = b.units / "tc_lab_test.service"
    return b


def setup(b, *args, ok=True):
    r = subprocess.run(["unshare", "-r", "bash", SETUP, *args], env=b.env,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       start_new_session=True, timeout=180)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, out
    assert "useradd" not in (b.log.read_text() if b.log.exists() else "")
    return out


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def shipped_profiles():
    return sorted(os.listdir(os.path.join(REPO, "profiles")))


def legacy_install(b):
    """A v9.2.1 install as it sits on disk: its code, with the state inside."""
    if subprocess.run(["git", "-C", REPO, "rev-parse", "-q", "--verify",
                       f"refs/tags/{LEGACY_TAG}"], capture_output=True).returncode:
        pytest.skip(f"tag {LEGACY_TAG} not available (shallow clone?)")
    arch = subprocess.run(["git", "-C", REPO, "archive", LEGACY_TAG],
                          capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(b.install)], input=arch, check=True)
    fake = {
        "users.json": json.dumps({"admin": {"hash": "$2b$12$fakefakefake", "role": "admin"},
                                  "ops": {"hash": "$2b$12$fakefakefak2", "role": "user"}}),
        "users.json.bak": "{}", "secret_key.txt": "ab" * 32,
        "cert.pem": "-----BEGIN CERTIFICATE-----\nfake\n", "key.pem": "fake key\n",
        "state.json": json.dumps({"eth1.100": {"latency_ms": 5.0}}),
        "network_config.json": json.dumps({"bridges": {}, "vlans": []}),
        "labels.json": json.dumps({"eth1.100": "uplink"}),
        "config.json": json.dumps({"idle_timeout_minutes": 45, "bind_address": "0.0.0.0",
                                   "port": 5000}),
        "restore_network.log": "old log\n",
        "users.json.20260101-000000.bak": "{}",
        "profiles/my_custom.json": json.dumps({"latency_ms": 42}),
    }
    for name, body in fake.items():
        (b.install / name).write_text(body)
    return {name: digest(b.install / name) for name in fake}


# ── Fresh install ─────────────────────────────────────────────────────────────
def test_fresh_install_puts_state_in_state_dir(box):
    out = setup(box)
    assert "Snapshot saved" not in out                      # nothing to snapshot yet

    cfg = json.loads((box.state / "config.json").read_text())
    assert cfg["port"] == 5000
    assert (box.state / "cert.pem").exists() and (box.state / "key.pem").exists()
    assert sorted(os.listdir(box.state / "profiles")) == shipped_profiles()
    for f in STATE_FILES:                                   # none of it with the code
        assert not (box.install / f).exists(), f
    assert oct((box.state).stat().st_mode & 0o777) == "0o700"


def test_unit_runs_as_service_user_and_writes_only_state(box):
    setup(box)
    unit = box.unit.read_text()
    assert "User=root" in unit and "Group=root" in unit     # TC_LAB_USER applied
    assert f"Environment=TC_LAB_STATE_DIR={box.state}" in unit
    assert f"ReadWritePaths={box.state}" in unit
    assert f"ReadWritePaths={box.install}" not in unit
    assert f"ExecStart={box.install}/venv/bin/python {box.install}/app.py" in unit
    rest = unit.replace(str(box.install), "").replace(str(box.state), "")
    assert "/opt/tc_lab" not in rest and "/var/lib/tc_lab" not in rest   # all rewritten


# ── v9.2.1 → v9.3 → rollback → v9.3 again ────────────────────────────────────
def test_upgrade_from_v921_moves_state_then_rolls_back(box):
    before = legacy_install(box)

    out = setup(box, "--keep-users")
    assert "Moving TC Lab's state" in out
    # Every state file moved byte-for-byte, and is gone from the code.
    for name, h in before.items():
        assert digest(box.state / name) == h, name
        if not name.startswith("profiles/"):
            assert not (box.install / name).exists(), name
    assert json.loads((box.state / "config.json").read_text())["idle_timeout_minutes"] == 45
    # User profile kept (in state), no longer mixed in with the shipped code.
    assert not (box.install / "profiles" / "my_custom.json").exists()
    assert set(shipped_profiles()) <= set(os.listdir(box.state / "profiles"))

    # The snapshot holds the v9.2.1 layout: state inside the code.
    snaps = sorted(p for p in box.backups.iterdir() if p.suffix == ".tgz")
    assert len(snaps) == 1
    with tarfile.open(snaps[0]) as t:
        names = set(t.getnames())
    assert "./users.json" in names and "./app.py" in names

    # Roll back: v9.2.1 code, its state back where v9.2.1 reads it, its unit.
    out = setup(box, "--rollback")
    assert "predates v9.3" in out
    assert (box.install / "app.py").read_text().startswith('"""app.py v9.2.1')
    for name, h in before.items():
        assert digest(box.install / name) == h, name
    unit = box.unit.read_text()
    assert "User=" not in unit and f"ReadWritePaths={box.install}" in unit

    # Used under v9.2.1 for a while, then upgraded again: the install
    # directory's state is the current one and must win over the stale copy.
    (box.install / "labels.json").write_text(json.dumps({"eth1.100": "changed"}))
    time.sleep(1.1)                                        # distinct snapshot name
    out = setup(box, "--keep-users")
    assert "held older state" in out
    assert json.loads((box.state / "labels.json").read_text()) == {"eth1.100": "changed"}
    assert list(box.root.joinpath("var", "lib").glob("tc_lab.replaced-*"))


# ── v9.3 → v9.3.x: snapshots carry the state directory ───────────────────────
def test_snapshot_includes_state_dir_and_rollback_restores_it(box):
    setup(box)
    labels = box.state / "labels.json"
    labels.write_text(json.dumps({"eth1.100": "before upgrade"}))
    setup(box, "--keep-users")                             # snapshot taken here
    labels.write_text(json.dumps({"eth1.100": "after upgrade"}))
    (box.state / "stray.json").write_text("{}")

    setup(box, "--rollback")
    assert json.loads(labels.read_text()) == {"eth1.100": "before upgrade"}
    assert not (box.state / "stray.json").exists()          # state mirrored exactly
    assert not (box.install / ".tc-lab-state").exists()     # never lands in the code


def test_reset_users_backs_up_in_state_dir(box):
    setup(box)
    (box.state / "users.json").write_text('{"admin": {"hash": "x", "role": "admin"}}')
    setup(box, "--reset-users")
    assert not (box.state / "users.json").exists()
    assert list(box.state.glob("users.json.*.bak"))


def test_state_dir_must_differ_from_install_dir(box):
    box.env["TC_LAB_STATE_DIR"] = str(box.install)
    out = setup(box, ok=False)
    assert "must not be the install directory" in out


# ── --port (v9.3) ─────────────────────────────────────────────────────────────
def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_fresh_install_with_port(box):
    port = free_port()
    out = setup(box, "--port", str(port))
    assert json.loads((box.state / "config.json").read_text())["port"] == port
    assert f":{port}" in out and f"port set to {port}" in out


def test_upgrade_with_port_keeps_other_settings(box):
    setup(box)
    cfg = box.state / "config.json"
    cfg.write_text(json.dumps({"idle_timeout_minutes": 45, "bind_address": "10.0.0.1",
                               "port": 5000}))
    port = free_port()
    setup(box, "--keep-users", "--port", str(port))
    assert json.loads(cfg.read_text()) == {"idle_timeout_minutes": 45,
                                           "bind_address": "10.0.0.1", "port": port}


@pytest.mark.parametrize("bad,msg", [("80", "between 1024"), ("x", "needs a number")])
def test_bad_port_stops_before_anything_changes(box, bad, msg):
    out = setup(box, "--port", bad, ok=False)
    assert msg in out
    assert not (box.install / "app.py").exists() and not box.state.exists()


def test_busy_port_stops_before_anything_changes(box):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        out = setup(box, "--port", str(s.getsockname()[1]), ok=False)
    assert "already listening" in out
    assert not (box.install / "app.py").exists() and not box.state.exists()


def test_low_port_from_old_install_is_flagged(box):
    legacy_install(box)
    cfg = json.loads((box.install / "config.json").read_text())
    (box.install / "config.json").write_text(json.dumps({**cfg, "port": 443}))
    out = setup(box, "--keep-users")
    assert "cannot listen below 1024" in out
    assert "Open:          https://" in out and ":5000" in out


# ── The installed unit is the source of truth (v9.3) ──────────────────────────
def test_upgrade_reuses_the_installed_state_dir_and_user(box):
    """A custom TC_LAB_STATE_DIR / TC_LAB_USER need not be repeated: an upgrade
    reads them back from the installed unit. (Fake root cannot create
    /var/lib/tc_lab, so falling back to the default would fail this test.)"""
    setup(box)
    (box.state / "labels.json").write_text('{"eth1.100": "kept"}')
    for var in ("TC_LAB_STATE_DIR", "TC_LAB_USER"):
        box.env.pop(var)
    setup(box, "--keep-users")
    assert json.loads((box.state / "labels.json").read_text()) == {"eth1.100": "kept"}
    unit = box.unit.read_text()
    assert f"ReadWritePaths={box.state}" in unit and "User=root" in unit


def test_stray_state_in_install_dir_never_replaces_the_real_state(box):
    """e.g. someone ran app.py by hand from /opt/tc_lab: those files are not
    the service's, and must not be taken for pre-v9.3 state to migrate."""
    setup(box)
    real = box.state / "users.json"
    real.write_text('{"admin": {"hash": "real", "role": "admin"}}')
    (box.install / "users.json").write_text('{"admin": {"hash": "stray", "role": "admin"}}')
    out = setup(box, "--keep-users")
    assert "does not use" in out
    assert json.loads(real.read_text())["admin"]["hash"] == "real"
    assert not list(box.root.joinpath("var", "lib").glob("tc_lab.replaced-*"))


@pytest.mark.parametrize("layout", ["v9.3", "pre-9.3"])
def test_tc_lab_command_uses_the_services_state_dir(box, layout):
    setup(box)
    store = box.state if layout == "v9.3" else box.install
    if layout == "pre-9.3":                     # a unit without TC_LAB_STATE_DIR
        box.unit.write_text("\n".join(l for l in box.unit.read_text().splitlines()
                                      if not l.startswith("Environment=TC_LAB_STATE_DIR")))
    (store / "users.json").write_text('{"admin": {"hash": "x", "role": "admin"}}')
    env = {k: v for k, v in box.env.items() if k != "TC_LAB_STATE_DIR"}
    r = subprocess.run(["unshare", "-r", "bash", str(box.install / "tc-lab"), "list-users"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"in {store}/users.json" in r.stdout


def test_snapshot_is_labelled_with_the_version(box):
    """--list-backups shows it; it used to read ".v9.2.1" (the dot of "app.py")."""
    legacy_install(box)
    setup(box, "--keep-users")
    label = next(box.backups.glob("*.tgz.version")).read_text().strip()
    assert label == "v9.2.1"
