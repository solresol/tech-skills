import os
import subprocess
import sys


def test_fetch_sector_aapl():
    env = dict(**os.environ, SANDBOX_HAS_DATABASE='no')
    result = subprocess.run(
        [sys.executable, 'fetch_sector.py', 'AAPL', '--dummy-run'],
        capture_output=True, text=True, env=env
    )
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0
    assert 'AAPL sector:' in result.stdout


if __name__ == '__main__':
    test_fetch_sector_aapl()

