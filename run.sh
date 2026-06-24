#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
PYTHONPATH=src streamlit run src/proofreader/ui/app.py
