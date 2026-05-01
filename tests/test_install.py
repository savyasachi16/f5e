import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL = REPO_ROOT / "install.sh"


def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_install_check_skips_claude_health_probe(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()

    for name in ("brew", "op", "jq", "gh", "sqlite3"):
        _write_exe(bindir / name, "#!/usr/bin/env bash\nexit 0\n")
    _write_exe(bindir / "plaid", "#!/usr/bin/env bash\nexit 1\n")

    _write_exe(
        bindir / "uv",
        "#!/usr/bin/env bash\nif [[ \"$1\" == sync && \"$2\" == --dry-run ]]; then\n"
        "  echo 'Resolved 0 packages'\n  exit 0\nfi\nexit 0\n",
    )
    _write_exe(
        bindir / "claude",
        "#!/usr/bin/env bash\nsleep 10\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["OSTYPE"] = "darwin-test"

    proc = subprocess.run(
        [str(INSTALL), "--check"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )

    assert proc.returncode == 0
    assert "Playwright MCP check skipped in --check mode" in proc.stdout
