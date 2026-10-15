#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export AGENT_ENGINE_RESOURCE_NAME="projects/898879548028/locations/us-east1/reasoningEngines/7099224423642693632"
export AGENT_DIRECTORY="app"
python main.py
