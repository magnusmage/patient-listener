#!/usr/bin/env bash
# Offline inference assets only; run after activating the existing GPU virtualenv.
set -euo pipefail
: "${VIRTUAL_ENV:?Activate the project virtual environment first}"
for tool in git make cc; do
  command -v "$tool" >/dev/null || { echo "Install git and build-essential first." >&2; exit 1; }
done
revision=6c9f20dc915b17f5619340069889db0aa007fcdc
source_dir="$VIRTUAL_ENV/src/patient-listener-flite-$revision"
mkdir -p "$VIRTUAL_ENV/src"
if [ ! -d "$source_dir" ]; then
  git clone https://github.com/festvox/flite.git "$source_dir"
fi
git -C "$source_dir" checkout --detach "$revision"
cd "$source_dir"
./configure --prefix="$VIRTUAL_ENV"
# Only the core and English lexicon libraries are needed by lex_lookup.
make -C src
make -C lang
make -C testsuite lex_lookup
install -m 755 testsuite/lex_lookup "$VIRTUAL_ENV/bin/lex_lookup"
python -m nltk.downloader -d "$VIRTUAL_ENV/nltk_data" cmudict
printf 'English pronunciation assets installed in %s\n' "$VIRTUAL_ENV"
