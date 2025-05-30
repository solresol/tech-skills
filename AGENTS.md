# Notes for Codex Agents

- The script `uvbootstrap.py` is executed when Codex sets up the environment. It downloads all Python dependencies using `uv`. If you recreate the environment manually, run `uv run uvbootstrap.py` to ensure requirements are installed.
- If the environment variable `SANDBOX_HAS_DATABASE` is set to `yes`, then PostgreSQL has been set up with the connection details stored in `db.conf`. If `SANDBOX_HAS_DATABASE` is `no`, envsetup.sh hasn't been executed and there is no point running it because you are in a sandbox without internet access.
