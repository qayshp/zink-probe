#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
SDK="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"
BUILD="$PWD/logs/android-runtime/build"
JAVA_HOME="$(/usr/libexec/java_home -v 21)"
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
mkdir -p "$BUILD/classes" "$BUILD/dex"
MANIFEST="$PWD/experiments/android-render/AndroidManifest.xml"
if [[ "${DISABLE_POINTER_TAGGING:-0}" == 1 ]]; then
 sed 's/<application /<application android:allowNativeHeapPointerTagging="false" /' "$MANIFEST" > "$BUILD/AndroidManifest.xml"
 MANIFEST="$BUILD/AndroidManifest.xml"
fi
"$SDK/build-tools/36.0.0/aapt" package -f -M "$MANIFEST" -I "$SDK/platforms/android-35/android.jar" -F "$BUILD/unsigned.apk"
javac -source 8 -target 8 -classpath "$SDK/platforms/android-35/android.jar" -d "$BUILD/classes" experiments/android-render/src/dev/zink/renderprobe/*.java
"$SDK/build-tools/36.0.0/d8" --lib "$SDK/platforms/android-35/android.jar" --output "$BUILD/dex" "$BUILD/classes/dev/zink/renderprobe/"*.class
(cd "$BUILD/dex" && zip -q -u "$BUILD/unsigned.apk" classes.dex)
if [[ ! -e "$BUILD/research.keystore" ]]; then
 keytool -genkeypair -keystore "$BUILD/research.keystore" -storepass research-only -keypass research-only -alias research -dname 'CN=Offline Zink Research' -keyalg RSA -validity 3650 >/dev/null 2>&1
fi
"$SDK/build-tools/36.0.0/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
"$SDK/build-tools/36.0.0/apksigner" sign --ks "$BUILD/research.keystore" --ks-pass pass:research-only --out "$BUILD/render-probe.apk" "$BUILD/aligned.apk"
