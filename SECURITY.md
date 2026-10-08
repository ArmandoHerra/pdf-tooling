# Security policy

## Supported versions

Security fixes are made for the latest minor release line only. Older lines get no backports. If you are on an older release, the remedy is to upgrade to the newest release on PyPI.

## Reporting a vulnerability

Do not open a public issue for a vulnerability.

Report it privately through GitHub private vulnerability reporting:

https://github.com/ArmandoHerra/pdf-tooling/security/advisories/new

Please include:

- the verb and the flags you ran, with paths and passwords replaced;
- the output of `pdftooling version -o json` and `pdftooling doctor -o json`;
- a description of the input (page count, size, encrypted or not, which application produced it).

If a reproducer file is needed, it must be a synthetic PDF made for the purpose, never a real or private document.

## What happens next

This is a single-maintainer project, and reports are handled on a best-effort basis. No response or fix time is promised.

A confirmed issue is fixed in a release and then disclosed through a GitHub security advisory, crediting the reporter if they wish. A CVE may be requested through that advisory when warranted.

## Scope

In scope: the `pdftooling` command line tool and the `pdf_tooling` package as published.

Examples of what we treat as a vulnerability:

- a password supplied through `--password-file` reaching argv, the environment, a log, an error message or an output;
- a write outside the requested destination, or over an existing file the command did not say it would replace;
- an encrypted input written as plaintext without `--allow-decrypted-output`;
- a document that makes the tool fetch a network resource.

Out of scope, and reported upstream instead: a defect inside LibreOffice, Tesseract or another engine or library itself.

Also out of scope: the project website.

What the LibreOffice hardening of `convert` does not cover is documented in the README, under "What this does not cover" in [OCR and Office conversion](README.md#ocr-and-office-conversion).
