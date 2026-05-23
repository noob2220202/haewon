#!/bin/bash
set -e

echo ">>> git pull"
git pull

echo ">>> pip install"
pip install -r requirements.txt -q

echo ">>> pm2 restart"
pm2 restart ecosystem.config.js

echo ">>> done"
pm2 status
