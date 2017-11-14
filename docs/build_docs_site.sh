#!/usr/bin/env bash
export PYTHONPATH=".."
make html
cp _build/html/_static/fonts/fontawesome-webfont.woff _build/html/_static/fonts/fontawesome-webfont.woff2
docker build -t tfnz/messidge_docs .
