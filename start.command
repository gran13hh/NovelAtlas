#!/bin/zsh

SCRIPT_DIR=${0:A:h}
cd "$SCRIPT_DIR" || exit 1

"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/scripts/dev.py"
STATUS=$?

if [[ $STATUS -ne 0 ]]; then
  echo
  read -k 1 "REPLY?启动失败，按任意键关闭窗口…"
  echo
fi

exit $STATUS
