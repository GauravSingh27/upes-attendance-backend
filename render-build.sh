#!/usr/bin/env bash
set -o errexit

# Install python dependencies
pip install -r requirements.txt

# Store Playwright binaries in the user cache directory
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/.cache/ms-playwright

# Install Chromium browser binary and system dependencies
playwright install chromium
playwright install-deps chromium