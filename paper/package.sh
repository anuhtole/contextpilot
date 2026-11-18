#!/bin/sh
# Build the paper and its submission packages into paper/dist/ (needs tectonic: brew install tectonic).
#   main.pdf                    named version, also copied to paper/main.pdf
#   contextpilot-arxiv.tar.gz   arXiv source upload (compiled once from a clean copy as a check)
#   contextpilot-anon.pdf       double-blind version: no author, no repository link
set -eu
cd "$(dirname "$0")"
mkdir -p dist/arxiv/figures dist/anon/figures
cp main.tex table_*.tex dist/arxiv/ && cp figures/*.pdf dist/arxiv/figures/
(cd dist/arxiv && tectonic main.tex >/dev/null 2>&1 && mv main.pdf ../main.pdf)
cp dist/main.pdf main.pdf
tar -czf dist/contextpilot-arxiv.tar.gz -C dist/arxiv .
cp table_*.tex dist/anon/ && cp figures/*.pdf dist/anon/figures/
sed 's/\\newif\\ifanon \\anonfalse/\\newif\\ifanon \\anontrue/' main.tex > dist/anon/main.tex
(cd dist/anon && tectonic main.tex >/dev/null 2>&1 && mv main.pdf ../contextpilot-anon.pdf)
ls -l dist/*.pdf dist/*.tar.gz
