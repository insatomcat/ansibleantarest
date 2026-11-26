#!/usr/bin/env python3
"""Turn the GDPR dialog of the web application into a notice with one button.

Upstream shows the text of webapp/src/assets/md/rgpd.md in a full-screen
dialog with Accept and Sign out, the latter logging the user out. A notice
that informs needs neither, so the dialog becomes a plain one with a single
Close, which records that the notice was shown exactly like Accept did. The
text itself is written by the play, next to this script.

Run against a fresh checkout (the play resets it on every run). Every edit is
an exact match that must be found once, so a change upstream stops the build
with the name of what moved instead of shipping a half-patched file.
"""
import re
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()


def once(old, new, text, regex=False):
    count = len(re.findall(old, text, flags=re.S)) if regex else text.count(old)
    if count != 1:
        sys.exit(f"{path}: expected exactly one match of {old!r}, found {count}. "
                 "The file changed upstream: adapt roles/antares_web/files/"
                 "patch_privacy_notice.py or empty antarest_privacy_notice.")
    return re.sub(old, new, text, flags=re.S) if regex else text.replace(old, new)


src = once('import ConfirmationDialog from "@/components/dialogs/ConfirmationDialog";\n',
           'import BasicDialog from "@/components/dialogs/BasicDialog";\n'
           'import { Button } from "@mui/material";\n', src)
# What only the Sign out button used. tsconfig has noUnusedLocals: leaving
# any of it behind fails the build.
src = once('import { logout } from "@/redux/ducks/auth";\n', "", src)
src = once('import useAppDispatch from "@/redux/hooks/useAppDispatch";\n', "", src)
src = once("  const dispatch = useAppDispatch();\n", "", src)
src = once(r"\n  const handleRejectGdpr = \(\) => \{\n    dispatch\(logout\(\)\);\n  \};\n", "", src,
           regex=True)
src = once(r"<ConfirmationDialog\b.*?</ConfirmationDialog>",
           """<BasicDialog
        open={openGdprDialog}
        title={t("gdpr.title")}
        titleIcon={PolicyIcon}
        actions={
          <Button variant="contained" onClick={handleAcceptGdpr}>
            {t("global.close")}
          </Button>
        }
      >
        <Markdown>{rgpd}</Markdown>
      </BasicDialog>""", src, regex=True)

for gone in ("ConfirmationDialog", "handleRejectGdpr", "useAppDispatch", "logout"):
    if gone in src:
        sys.exit(f"{path}: {gone} is still referenced after the patch.")

open(path, "w", encoding="utf-8").write(src)
print(f"patched {path}")
