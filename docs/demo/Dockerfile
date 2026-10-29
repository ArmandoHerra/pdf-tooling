# syntax=docker/dockerfile:1.28.0@sha256:bb22d9815c728170f72750f4e5b0d672e06176142e1d602c7e66c050100b7e5b
# PDF-153: the demo render image. Every input pinned; move a pin only with a re-render.
FROM ghcr.io/charmbracelet/vhs:v0.12.1@sha256:ea49a6a1c529be83153e88321892b5585964418f0b9055e8c1e0d732194234a3
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /usr/local/bin/
ADD --checksum=sha256:b1c22172dd303f3be49e935aa56aa48a8b7a46e0bc838b4997d3bb451495870f --chmod=0755 https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-linux-amd64 /usr/local/bin/jq
ENV UV_PROJECT_ENVIRONMENT=/opt/v UV_PYTHON=3.13 UV_LINK_MODE=copy UV_BUILD_CONSTRAINT=/opt/build-constraints.txt PYTHONDONTWRITEBYTECODE=1
RUN printf 'hatchling==1.33.0\n' > /opt/build-constraints.txt && uv python install 3.13
