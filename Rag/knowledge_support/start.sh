#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
exec .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
