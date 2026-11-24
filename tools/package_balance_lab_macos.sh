#!/bin/sh
# Build a portable macOS app and disk image. Run from any directory.
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$repo"
desktop="$source_dir/desktop"
output_dir=${1:-"$repo/builds/balance-lab-macos"}
mkdir -p "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)
name='Age of Collapse Balance Lab'
image="$output_dir/Age-of-Collapse-Balance-Lab-macOS.dmg"
if [ -e "$image" ]; then
    echo "An image already exists at $image. Pass a new output directory to rebuild." >&2
    exit 1
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/balance-lab-package.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM

python_version=3.13.12
release=20260325
archives=${AOC_RUNTIME_ARCHIVES:-"$work/archives"}
mkdir -p "$archives"
archive() {
    path="$archives/$1"
    if [ ! -f "$path" ]; then
        curl --fail --silent --show-error --location "$2" --output "$path.download"
        mv "$path.download" "$path"
    fi
    actual=$(shasum -a 256 "$path" | cut -d ' ' -f 1)
    if [ "$actual" != "$3" ]; then
        echo "Checksum mismatch for $path" >&2
        exit 1
    fi
}
python_base="https://releases.astral.sh/github/python-build-standalone/releases/download/$release/cpython-$python_version%2B$release"
archive aarch64.tar.gz "$python_base-aarch64-apple-darwin-install_only_stripped.tar.gz" \
    053b5062a711c7a07f402d2e9a43c65566e9b750478a10dad9093dad1b814fe5
archive x86_64.tar.gz "$python_base-x86_64-apple-darwin-install_only_stripped.tar.gz" \
    5f8c73129d3765bbbdcf771decf96135596f9e3e205b08ae7cf1fe2fc0cdaf68
archive upstream.tar.gz "https://codeload.github.com/astral-sh/python-build-standalone/tar.gz/refs/tags/$release" \
    c6b5d75ad4147c6aca77b70891573d0037c3795d561060e935299800263cc9ca

stage="$work/disk"
app="$stage/$name.app"
contents="$app/Contents"
simulator="$contents/Resources/Simulator"
runtime="$contents/Resources/Runtimes"
licenses="$contents/Resources/Third-Party-Licenses"
mkdir -p "$contents/MacOS" "$runtime" "$licenses" "$simulator/playtests"
cp "$desktop/Info.plist" "$contents/Info.plist"
cp "$desktop/server_entry.py" "$simulator/server_entry.py"
for module in "$source_dir"/*.py; do
    case "$(basename "$module")" in
        test_*) continue ;;
    esac
    cp "$module" "$simulator/"
done
ditto "$source_dir/static" "$simulator/static"
cp "$source_dir/playtests/deep_upside_no_cache.json" "$source_dir/playtests/combat_playtest.json" \
    "$source_dir/playtests/rolled_combat_playtest.json" "$simulator/playtests/"

unpack_runtime() {
    mkdir -p "$2"
    tar -xzf "$1" -C "$2" --strip-components 1 \
        --exclude '*/__pycache__/*' --exclude '*.pyc' --exclude '*/include/*' \
        --exclude '*/site-packages/*' --exclude '*/ensurepip/*'
    find "$2" -type f \( -name 'python3.13' -o -name '*.dylib' -o -name '*.so' \) \
        -exec sh -ec 'for binary do codesign --force --sign - "$binary" 2>/dev/null; done' sh {} +
    codesign --verify "$2/bin/python3.13"
}
unpack_runtime "$archives/aarch64.tar.gz" "$runtime/Python-arm64"
unpack_runtime "$archives/x86_64.tar.gz" "$runtime/Python-x86_64"
tar -xzf "$archives/upstream.tar.gz" -C "$licenses" --strip-components 1 \
    --include "python-build-standalone-$release/LICENSE*" \
    --include "python-build-standalone-$release/python-licenses.rst"

compile() {
    architecture=$1
    xcrun swiftc -swift-version 5 -target "$architecture-apple-macos13.0" \
        -O -module-cache-path "$work/module-cache-$architecture" "$desktop/BalanceLab.swift" \
        -o "$work/BalanceLab-$architecture"
}
compile arm64 &
arm_build=$!
compile x86_64 &
intel_build=$!
wait "$arm_build"
wait "$intel_build"
xcrun lipo -create "$work/BalanceLab-arm64" "$work/BalanceLab-x86_64" \
    -output "$contents/MacOS/BalanceLab"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
ln -s /Applications "$stage/Applications"
hdiutil create -quiet -volname "$name" -srcfolder "$stage" -format UDZO "$image"
printf '%s\n' "$image"
