# pdf-tooling demo: merge, compress, and preview a batch.
#
# Rendered with VHS v0.12.1 (https://github.com/charmbracelet/vhs). From the repository root:
#
#   docker run --rm -v "$PWD":/vhs ghcr.io/charmbracelet/vhs:v0.12.1 docs/demo/pdf-tooling.tape
#
# The hidden prelude installs the pinned release into a venv inside the container,
# so the recording shows the release a visitor gets, never an unreleased tree.
# Recorded pdf-tooling version: 1.1.0 (the PyPI release in force at landing).
#
# The GIF is linked from README.md by an absolute raw.githubusercontent.com URL that
# PyPI pages of older releases keep forever: re-render over the same path, never rename.
# Encrypt is not shown because passwords would be typed on screen; OCR is not shown
# because the recording container has no tesseract.

Output docs/demo/pdf-tooling.gif

Set Shell bash
Set FontSize 16
Set Width 1200
Set Height 520
Set Padding 16
Set TypingSpeed 45ms
Set Framerate 12
Env PS1 "$ "

Hide
Type `export DEBIAN_FRONTEND=noninteractive && apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq python3-venv jq >/dev/null 2>&1 && python3 -m venv /opt/v && /opt/v/bin/pip install -q pdf-tooling==1.1.0 && echo INS''TALLED` Enter
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
