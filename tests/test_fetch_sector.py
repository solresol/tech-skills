import os
import subprocess
import sys
from pathlib import Path


def test_fetch_sector_aapl():
    env = dict(**os.environ, SANDBOX_HAS_DATABASE='no', USE_YFINANCE_STUB='1')
    repo_root = Path(__file__).resolve().parents[1]
    venv_python = repo_root / '.venv' / 'bin' / 'python'
    executable = str(venv_python if venv_python.exists() else sys.executable)
    result = subprocess.run(
        [executable, 'fetch_sector.py', 'AAPL', '--dummy-run'],
        capture_output=True, text=True, env=env
    )
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0
    assert 'AAPL sector:' in result.stdout


if __name__ == '__main__':
    test_fetch_sector_aapl()

