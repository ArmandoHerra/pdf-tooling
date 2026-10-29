#!/usr/bin/env bash
# Re-render docs/demo/pdf-tooling.gif and docs/demo/pdf-tooling.txt from THIS tree,
# inside the pinned image built from docs/demo/Dockerfile. Installs nothing on the host;
# needs only docker. Run from anywhere inside the checkout.
# Usage: bash docs/demo/render.sh        (-h / --help prints this text)
# Tear-down (optional): docker image rm pdf-tooling-demo-render:local
set -euo pipefail
case "${1:-}" in
  -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
esac
if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required for docs/demo/render.sh but was not found on PATH" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "error: docker is installed but its daemon is not reachable (docker info failed)" >&2
  exit 1
fi
root="$(git rev-parse --show-toplevel)"
cd "$root"
image="pdf-tooling-demo-render:local"
docker build --platform linux/amd64 -f docs/demo/Dockerfile -t "$image" docs/demo
handback() {  # every uid-0 path under the tree back to the invoking user, via the pinned image
  docker run --rm --platform linux/amd64 -v "$root":/vhs --entrypoint chown "$image" \
    -R -h --from=0 "$(id -u):$(id -g)" /vhs
}
trap handback EXIT
docker run --rm --platform linux/amd64 -v "$root":/vhs "$image" docs/demo/pdf-tooling.tape
handback
trap - EXIT
sha256sum docs/demo/pdf-tooling.gif docs/demo/pdf-tooling.txt
