#!/bin/bash
# ダブルクリックでGUIを起動（開発/テスト用。正式配布は実行ファイル化後）
cd "$(dirname "$0")"
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
python -m tcg_linker.gui
