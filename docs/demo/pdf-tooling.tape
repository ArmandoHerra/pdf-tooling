# pdf-tooling demo: merge, compress, and preview a batch.
#
# Rendered with VHS v0.12.1 (https://github.com/charmbracelet/vhs) in the pinned image
# ghcr.io/charmbracelet/vhs:v0.12.1@sha256:ea49a6a1c529be83153e88321892b5585964418f0b9055e8c1e0d732194234a3
# extended by docs/demo/Dockerfile (uv 0.13.5, Python 3.13 managed by uv: CPython 3.13.17).
# From the repository root:
#
#   bash docs/demo/render.sh
#
# which builds the image and runs, inside it:
#
#   docker run --rm --platform linux/amd64 -v "$PWD":/vhs pdf-tooling-demo-render:local docs/demo/pdf-tooling.tape
#
# The hidden prelude installs the checked-out tree with uv sync --frozen (OR-72), so the
# recording shows what the tree prints. Nothing is installed on the host.
# Recorded pdf-tooling version: 1.3.0 (the checked-out tree, installed by uv sync --frozen; OR-72).
#
# The GIF is linked from README.md by an absolute raw.githubusercontent.com URL that
# PyPI pages of older releases keep forever: re-render over the same path, never rename.
# The text transcript (docs/demo/pdf-tooling.txt) comes from the same run, so a test can
# read the compress row without OCR.
# Encrypt is not shown because passwords would be typed on screen; OCR is not shown
# because the recording container has no tesseract.

Output docs/demo/pdf-tooling.gif
Output docs/demo/pdf-tooling.txt

Set Shell bash
Set FontSize 16
Set Width 1200
Set Height 520
Set Padding 16
Set TypingSpeed 45ms
Set Framerate 12
Env PS1 "$ "

Hide
Type `cd /vhs && uv sync --frozen --no-dev -q >/dev/null 2>&1 && echo INS''TALLED` Enter
Wait+Screen@240s /INSTALLED/
Type `export PATH=/opt/v/bin:$PATH && mkdir /tmp/demo && cd /tmp/demo` Enter
Type `for n in 1 2; do python -c "from reportlab.pdfgen.canvas import Canvas as C; c=C('chapter$n.pdf'); c.drawString(72,720,'Chapter $n'); c.showPage(); c.save()"; done` Enter
Type `clear` Enter
Sleep 500ms
Show

Type "pdftooling merge chapter1.pdf chapter2.pdf -O book.pdf" Sleep 600ms Enter
Sleep 2s
Type "pdftooling compress book.pdf -O book-small.pdf" Sleep 600ms Enter
Sleep 2s
Type `pdftooling --dry-run compress chapter1.pdf chapter2.pdf --out-dir small -o json | jq -r '.items[] | "\(.input) -> \(.output) ok=\(.ok)"'` Sleep 600ms Enter
Sleep 3s
Type "ls" Sleep 400ms Enter
Sleep 3s
