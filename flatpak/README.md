# The Flatpak

`com.jacksonv.Kami.yml` builds Kami on KDE's Flatpak runtime; the main README
has the build commands.

## Qt and PySide

The base app's PySide6 uses Qt's private API, which is tied to one exact Qt
release, and KDE's runtime and Qt's base app update separately. When the
runtime moves to a new Qt first, no window opens, and Kami's log ends in
`could not import module 'PySide6.QtCore'`, until the base app catches up. It
then needs rebuilding, since the build copies PySide6 out of the base app.

## Python packages

The runtime has no Pygments, which colours the preview's code blocks, so it
comes from PyPI, pinned in `requirements.txt`. `python3-deps.yaml` gives the
download and its checksum, in the format flatpak-builder-tools'
[flatpak-pip-generator](https://github.com/flatpak/flatpak-builder-tools/tree/master/pip)
writes, so the build itself needs no network. After changing the pin,
regenerate it from the repository root, in the SDK the app builds with:

```bash
mkdir -p build/pipgen
curl -fsSLo build/pipgen/flatpak-pip-generator.py \
    https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator.py
flatpak run --share=network --filesystem="$PWD" --command=sh org.kde.Sdk//6.11 -c '
    cd flatpak
    python3 -m pip install -q --target ../build/pipgen/deps packaging requirements-parser pyyaml
    PYTHONPATH=../build/pipgen/deps python3 ../build/pipgen/flatpak-pip-generator.py \
        --yaml --requirements-file requirements.txt --output python3-deps'
```
