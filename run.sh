#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m cleaning_workspace
