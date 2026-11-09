#!/bin/zsh
# Mirror this checkout to the Mac mini test host (ssh alias `mini`) and, with --setup, install toolchains there.
# usage: scripts/sync-mini.sh [--setup]
set -e
SRC=${0:a:h:h}
rsync -az --delete \
  --exclude node_modules --exclude .venv --exclude .build --exclude DerivedData --exclude __pycache__ \
  --exclude 'video/out' --exclude 'data/api.sqlite' --exclude 'data/*.log' --exclude '.git' \
  "$SRC/" mini:flowline/
scp -q "$SRC/.env" mini:flowline/.env && ssh mini chmod 600 flowline/.env
echo "synced -> mini:~/flowline"
if [[ "$1" == "--setup" ]]; then
ssh mini 'bash -lc "
set -e
cd ~/flowline
uv python install 3.12 >/dev/null 2>&1 || true
for d in flowline1 api executor; do
  if [ -f \$d/pyproject.toml ]; then (cd \$d && uv sync -q && echo \"\$d: uv sync ok\"); fi
done
if [ -f board/package.json ]; then
  command -v pnpm >/dev/null || npm i -g pnpm >/dev/null 2>&1
  (cd board && pnpm i --silent && echo \"board: pnpm i ok\")
fi
echo setup done
"'
fi
