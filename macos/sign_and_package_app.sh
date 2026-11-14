#!/bin/bash -eux

_root_dir="$(dirname "$(greadlink -f "$0")")"
_repo_dir="$(dirname "$_root_dir")"
_bundle_id="com.manuelmezzanotte.sail"
_app="out/Default/Sail.app"
_packaging="out/Default/Sail Packaging"

# Paths below are relative to the Chromium source tree.
cd "$_repo_dir/build/src"

if [ -n "${MACOS_CERTIFICATE_NAME:-}" ]; then
  if [ -n "${PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH:-}" ]; then
    # Chromium embeds this profile from its packaging inputs during signing.
    cp "$PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH" "$_packaging/Sail.provisionprofile"
  fi

  CREDENTIAL_ARGS=(store-credentials notarytool-profile)
  NOTARY_ARGS=(--notary-arg=--keychain-profile=notarytool-profile)
  if [ -n "${CI:-}" ]; then
    CREDENTIAL_ARGS+=("--keychain=$HOME/Library/Keychains/build.keychain-db")
    NOTARY_ARGS+=("--notary-arg=--keychain=$HOME/Library/Keychains/build.keychain-db")
  fi

  xcrun notarytool \
    "${CREDENTIAL_ARGS[@]}" \
    --apple-id "$PROD_MACOS_NOTARIZATION_APPLE_ID" \
    --team-id "$PROD_MACOS_NOTARIZATION_TEAM_ID" \
    --password "$PROD_MACOS_NOTARIZATION_PWD"

  python3 "$_packaging/sign_chrome.py" \
    --input out/Default \
    --output out/Default/signed \
    --identity "$MACOS_CERTIFICATE_NAME" \
    --disable-packaging --notarize \
    "${NOTARY_ARGS[@]}"

  _app="out/Default/signed/stable/Sail.app"
else
  echo "warn: MACOS_CERTIFICATE_NAME is missing; skipping notarization" >&2
  # A local self-signed certificate gives every build the same code identity,
  # so the keychain keeps "Always Allow" for the Sail Storage Key. Signed ad
  # hoc, Sail looks like a new app after each build and macOS asks again.
  _local_identity="${SAIL_LOCAL_SIGNING_IDENTITY:-Sail Local Signing}"
  if security find-identity -p codesigning | grep -qF "\"$_local_identity\""; then
    codesign --force --deep --sign "$_local_identity" "$_app"
  else
    echo "warn: no \"$_local_identity\" certificate; signing ad hoc" >&2
    codesign --force --deep --sign - "$_app"
  fi
fi

if [ -z "${OUT_DMG_PATH:-}" ]; then
  _chromium_version=$(cat "$_repo_dir/helium-chromium/chromium_version.txt")
  _helium_revision=$(cat "$_repo_dir/helium-chromium/revision.txt")
  _platform_revision=$(cat "$_root_dir/revision.txt")
  OUT_DMG_PATH="$_repo_dir/build/sail_${_chromium_version}-${_helium_revision}.${_platform_revision}_macos.dmg"
fi

# Package the app
chrome/installer/mac/pkg-dmg \
  --sourcefile --source "$_app" \
  --target "$OUT_DMG_PATH" \
  --volname Sail --format ULMO \
  --icon "$_app/Contents/Resources/app.icns" \
  --symlink /Applications:/Applications \
  --mkdir .background \
  --copy "$_repo_dir/sail/resources/dmg_background.png:/.background/dmg_background.png" \
  --copy "$_root_dir/resources/dmg_dsstore:/.DS_Store" \
  --verbosity 2

if [ -n "${MACOS_CERTIFICATE_NAME:-}" ]; then
  codesign \
    --sign "$MACOS_CERTIFICATE_NAME" \
    --identifier "$_bundle_id" --force \
    "$OUT_DMG_PATH"
fi
