#!/usr/bin/env bash
# 从 data-snapshot 分支拉取 GitHub Actions 生成的行情快照与报告，并在本地用 csv 数据源复算。
# 用法：bash scripts/pull_snapshot.sh [额外 run 参数]
set -euo pipefail
cd "$(dirname "$0")/.."
git fetch -q origin data-snapshot
rm -rf data/snapshot && mkdir -p data/snapshot
git archive origin/data-snapshot | tar -x -C data/snapshot
mkdir -p data/snapshot_csv
cp data/snapshot/history.csv data/snapshot_csv/all.csv
echo "快照提交：$(git log -1 --format='%s (%ci)' origin/data-snapshot)"
CONFIG_ARG=()
if [ -f config.yaml ]; then CONFIG_ARG=(--config config.yaml); fi
python -m daily_report run "${CONFIG_ARG[@]}" --source csv --csv-dir data/snapshot_csv "$@"
