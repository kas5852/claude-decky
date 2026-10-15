#!/bin/bash
set -euo pipefail
version=${WHISPER_VERSION:-v1.9.5}
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$root/bin"
docker run --rm --platform linux/amd64 -v "$root/bin:/out" ubuntu:22.04 bash -euc "
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git cmake g++ make ca-certificates >/dev/null
git clone -q --depth 1 --branch $version https://github.com/ggml-org/whisper.cpp /src
cmake -S /src -B /build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF \
  -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BMI2=ON -DGGML_AVX_VNNI=ON \
  -DGGML_OPENMP=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_SDL2=OFF \
  -DCMAKE_EXE_LINKER_FLAGS='-static-libgcc -static-libstdc++' >/dev/null
cmake --build /build --target whisper-cli -j\$(nproc) >/dev/null
strip /build/bin/whisper-cli
cp /build/bin/whisper-cli /out/whisper-cli
"
ls -la "$root/bin/whisper-cli"
