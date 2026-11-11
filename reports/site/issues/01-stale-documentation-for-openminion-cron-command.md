# Stale documentation for openminion cron command

**Summary**: The documentation suggests `openminion cron tick` as a valid command, but `cli_help` shows no such subcommand.

**Where**: `docs__guides__scheduled-tasks.md`, line 98.

**Steps to reproduce**:
1. Refer to the documentation.
2. Attempt to run the `openminion cron tick` command.

**Expected**: The documentation states `openminion cron tick` is a valid subcommand.

**Actual**: The command is not recognized by the `openminion cron` command.

**Suggested fix**: Remove or rewrite the passage as `tick` is an internal function, not a standalone command.

**Environment**: openminion 0.1.20 installed from PyPI.
