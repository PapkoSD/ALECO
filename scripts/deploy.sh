#!/bin/sh
# Publish site/ to the gh-pages branch, which GitHub Pages serves at https://papkosd.github.io/ALECO/
# Commit your changes on main first, then:  sh scripts/deploy.sh
# (An optional argument is added to the deploy commit message.)
set -e
cd "$(dirname "$0")/.."
if [ -n "$(git status --porcelain -- site)" ]; then
  echo "site/ has changes that are not committed yet. Commit them on main first."; exit 1
fi
git fetch -q origin gh-pages 2>/dev/null || true
tree=$(git rev-parse HEAD:site)
parent=$(git rev-parse -q --verify origin/gh-pages || true)
message="Deploy site from main $(git rev-parse --short HEAD)"
[ -n "$1" ] && message=$(printf '%s\n\n%s' "$message" "$1")
commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "$message")
git push -q origin "$commit:refs/heads/gh-pages"
echo "Deployed $(git rev-parse --short "$commit"). GitHub Pages updates in a minute or two: https://papkosd.github.io/ALECO/"
