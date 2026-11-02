#!/bin/zsh
# Notarize TMsearch.app and wrap it in a distributable DMG — v1.0.1
#
# Run ./build.sh first; this takes dist/TMsearch.app as it finds it.
#
# Both the app and the DMG are notarized and stapled: the app because that
# is what gets dragged out of the DMG, the DMG because that is what gets
# downloaded. Notarization uses the "PixProNotary" keychain profile, so no
# password lives here. To recreate the profile:
#   xcrun notarytool store-credentials "PixProNotary" \
#       --apple-id <appleid> --team-id RUDN8D7ZN9
set -e
cd "${0:A:h}"

SIGN_ID="4208ABA3EC12F24C1F09C7BB624EFF68B44259DB"
PROFILE="PixProNotary"
APP="dist/TMsearch.app"

[[ -d "$APP" ]] || { echo "error: $APP not found — run ./build.sh first" >&2; exit 1; }

VERSION=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")
DMG="dist/TMsearch-${VERSION}.dmg"

xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1 \
    || { echo "error: no notary profile '$PROFILE' in keychain" >&2; exit 1; }

echo "==> notarizing the app (TMsearch $VERSION)"
rm -f dist/TMsearch_notarize.zip
ditto -c -k --keepParent "$APP" dist/TMsearch_notarize.zip
xcrun notarytool submit dist/TMsearch_notarize.zip --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP"

echo "==> building the disk image"
rm -rf dist/dmg "$DMG"
mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
cat > "dist/dmg/READ ME FIRST.txt" <<READMEEOF
TMsearch $VERSION

INSTALLING
    Drag TMsearch onto the Applications folder beside it.

FULL DISK ACCESS - REQUIRED
    macOS only lets an app read Time Machine backups if it has Full Disk
    Access. Turn it on in:

        System Settings > Privacy & Security > Full Disk Access

    for TMsearch (to use it from Finder), and for Terminal (to use the
    tmsearch command). Without it, TMsearch finds no backups.

THE TMSEARCH COMMAND
    Installing with Homebrew adds it for you:

        brew install --cask spurious-cox/tap/tmsearch

    Installed from this disk image, run it as:

        /Applications/TMsearch.app/Contents/Resources/tmsearch

https://github.com/spurious-cox/tmsearch
READMEEOF
for attempt in 1 2 3 4 5; do
    if hdiutil create -volname "TMsearch" -srcfolder dist/dmg -ov \
            -format UDZO "$DMG" >/dev/null 2>dist/hdiutil.err; then
        break
    fi
    echo "    hdiutil attempt $attempt failed: $(tr -d '\n' < dist/hdiutil.err)"
    [[ $attempt == 5 ]] && { echo "error: could not build the disk image" >&2; exit 1; }
    sleep 5
done
rm -rf dist/dmg dist/hdiutil.err

echo "==> signing and notarizing the disk image"
codesign --force --timestamp --sign "$SIGN_ID" "$DMG"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"

echo "==> installing the stapled app to /Applications"
rm -rf /Applications/TMsearch.app
cp -R "$APP" /Applications/
xattr -dr com.apple.quarantine /Applications/TMsearch.app 2>/dev/null || true

echo "==> updating the Homebrew cask"
CASK="$(brew --repository 2>/dev/null)/Library/Taps/spurious-cox/homebrew-tap/Casks/tmsearch.rb"
if [[ -f "$CASK" ]]; then
    SHA=$(shasum -a 256 "$DMG" | cut -d" " -f1)
    /usr/bin/sed -i "" \
        -e "s/^  version \".*\"/  version \"$VERSION\"/" \
        -e "s/^  sha256 \".*\"/  sha256 \"$SHA\"/" "$CASK"
    echo "    $CASK -> $VERSION ($SHA)"
else
    echo "    no cask at $CASK — skipped"
fi

echo "==> results"
echo "    dmg:      $DMG  ($(du -h "$DMG" | cut -f1))"
echo "    stapled:  app $(xcrun stapler validate "$APP" >/dev/null 2>&1 && echo YES || echo no), dmg $(xcrun stapler validate "$DMG" >/dev/null 2>&1 && echo YES || echo no)"
spctl -a -t open --context context:primary-signature -v "$DMG" 2>&1 | sed 's/^/    gatekeeper: /'
