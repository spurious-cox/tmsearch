#!/bin/zsh
# Build, sign and install TMsearch.app — v1.0.0
#
#   ./build.sh                build, sign, install to /Applications
#   ./build.sh --no-install   build and sign into dist/ only
#
# Signing a py2app bundle:
#   * `codesign --deep` is not enough. It skips the .so files under
#     Resources/lib and the extension-less Mach-O at Contents/MacOS/python,
#     and notarization rejects exactly those. `file` decides what is a
#     Mach-O; filenames do not.
#   * --options runtime (hardened runtime) is required for notarization.
#   * The identity is chosen by SHA-1 hash, because older certificates with
#     similar names are still in the keychain.
#   * --timestamp keeps the signature valid after the certificate expires.
set -e
cd "${0:A:h}"

SIGN_ID="4208ABA3EC12F24C1F09C7BB624EFF68B44259DB"
APP="dist/TMsearch.app"

if ! security find-identity -p codesigning | grep -q "$SIGN_ID"; then
    echo "error: signing identity $SIGN_ID not in keychain" >&2
    exit 1
fi

echo "==> building"
rm -rf build dist
./venv/bin/python setup.py py2app >/dev/null
# py2app copies data files without their exec bit.
chmod +x "$APP/Contents/Resources/tmsearch"

echo "==> checking nothing signable is hidden inside the zip"
ZIP=$(echo $APP/Contents/Resources/lib/python3*.zip)
HIDDEN=$(./venv/bin/python -c "import zipfile,sys;print(len([n for n in zipfile.ZipFile(sys.argv[1]).namelist() if n.endswith(('.dylib','.so'))]))" "$ZIP")
[[ "$HIDDEN" == 0 ]] || { echo "error: $HIDDEN binaries inside $ZIP cannot be signed" >&2; exit 1; }

echo "==> signing inner binaries with the hardened runtime"
find "$APP" -type f -print0 | while IFS= read -r -d $'\0' f; do
    if file -b "$f" | grep -q 'Mach-O'; then
        codesign --force --timestamp --options runtime --sign "$SIGN_ID" "$f" 2>/dev/null
    fi
done

echo "==> sealing nested frameworks, then the app"
find "$APP" -name '*.framework' -print0 \
    | xargs -0 -n1 -I{} codesign --force --timestamp --options runtime --sign "$SIGN_ID" {} 2>/dev/null || true
codesign --force --timestamp --options runtime \
    --entitlements tmsearch.entitlements --sign "$SIGN_ID" "$APP"
codesign --verify --deep --strict "$APP"
echo "    architectures: $(lipo -archs $APP/Contents/MacOS/TMsearch)"

if [[ "$1" != "--no-install" ]]; then
    echo "==> installing to /Applications"
    rm -rf /Applications/TMsearch.app
    cp -R "$APP" /Applications/
    xattr -dr com.apple.quarantine /Applications/TMsearch.app 2>/dev/null || true
    codesign -dv /Applications/TMsearch.app 2>&1 | grep -E "Identifier=|TeamIdentifier="
    plutil -extract CFBundleShortVersionString raw /Applications/TMsearch.app/Contents/Info.plist
fi
