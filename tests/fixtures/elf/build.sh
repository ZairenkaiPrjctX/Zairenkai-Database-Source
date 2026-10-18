#!/usr/bin/env bash
# Rebuild the ELF fixtures from src/. Requires clang and lld. Outputs are committed so tests
# do not need a cross toolchain; this script documents exactly how they were produced.
set -euo pipefail
cd "$(dirname "$0")"
build() {  # target outdir linker
  local t=$1 out=$2 linker=$3
  mkdir -p "$out"
  local cc=(clang --target="$t" -fuse-ld=lld -nostdlib -fPIC -O1 "-Wl,--build-id=none")
  "${cc[@]}" -shared -Wl,-soname,libfixture_dep.so -o "$out/libfixture_dep.so" src/libfixture_dep.c
  "${cc[@]}" -shared -Wl,-soname,libmissing_fixture.so -o /tmp/libmissing_fixture.$$.so src/libmissing_fixture.c
  "${cc[@]}" -shared -Wl,-soname,libthermal_fixture.so -o "$out/libthermal_fixture.so" \
    src/libthermal_fixture.c "$out/libfixture_dep.so" /tmp/libmissing_fixture.$$.so
  "${cc[@]}" -pie -Wl,-e,_start_fixture -Wl,--dynamic-linker="$linker" \
    -o "$out/thermal_service" src/thermal_service.c "$out/libthermal_fixture.so"
  rm -f /tmp/libmissing_fixture.$$.so
}
build aarch64-linux-android arm64 /system/bin/linker64
build armv7a-linux-androideabi arm /system/bin/linker
