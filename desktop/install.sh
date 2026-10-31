#!/bin/bash
# Install Kami's desktop integration into the user's home directory:
#   - the kami launcher on PATH, symlinked to this checkout's bin/
#   - the .desktop entry and its icon
#   - Kami as the default for plain text and Markdown files
#
# Files land in:
#   ~/bin/kami                                        (symlink)
#   ~/.local/share/applications/kami.desktop
#   ~/.local/share/icons/hicolor/scalable/apps/kami.svg
#   ~/.config/mimeapps.list                           (default-application entries)
#
# With --flatpak, the Kami Flatpak brings its own launcher, entry and icon,
# so this only makes it the default, for the same types.
#
# The entry's keywords include "notepad", "note" and "memo", so typing any
# of them into the app launcher finds Kami.
#
# Run from anywhere — paths resolve relative to the checkout. Safe to
# re-run; re-run it after moving the checkout. Installs no packages —
# README.md has the dnf line.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
BIN_DIR="${HOME}/bin"
APPS_DIR="${DATA_HOME}/applications"
ICON_DIR="${DATA_HOME}/icons/hicolor/scalable/apps"

KAMI_TYPES=(text/plain text/markdown)

if [[ "${1:-}" == "--flatpak" ]]; then
    KAMI_ENTRY=com.jacksonv.Kami.desktop
    if ! flatpak info com.jacksonv.Kami >/dev/null 2>&1; then
        echo "The com.jacksonv.Kami Flatpak isn't installed; README.md has the build line." >&2
        exit 1
    fi
else
    KAMI_ENTRY=kami.desktop

    mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICON_DIR}"

    # --- Launcher: a symlink, so it always runs this checkout ---
    if [[ -e "${BIN_DIR}/kami" && ! -L "${BIN_DIR}/kami" ]]; then
        echo "${BIN_DIR}/kami exists and isn't a symlink; move it aside and re-run." >&2
        exit 1
    fi
    ln -sfn "${PROJECT_ROOT}/bin/kami" "${BIN_DIR}/kami"
    echo "Linked launcher: ${BIN_DIR}/kami"

    # --- Icon (the entry says Icon=kami) ---
    cp "${PROJECT_ROOT}/kami/resources/kami.svg" "${ICON_DIR}/kami.svg"
    echo "Wrote icon: ${ICON_DIR}/kami.svg"

    # --- .desktop entry: substitute the absolute project root into Exec ---
    sed "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" "${SCRIPT_DIR}/kami.desktop.in" \
        > "${APPS_DIR}/kami.desktop"
    echo "Wrote desktop entry: ${APPS_DIR}/kami.desktop"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${APPS_DIR}"
        echo "Refreshed desktop database"
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -t -f "${DATA_HOME}/icons/hicolor" 2>/dev/null || true
    fi
fi

# --- Default applications ---
# gio rather than xdg-mime, for the reason in Pepper's install.sh: under
# KDE 6, xdg-utils 1.2.1 shells out to an unversioned `qtpaths` that Fedora
# doesn't ship, and still exits 0 when it fails to write mimeapps.list.
for type in "${KAMI_TYPES[@]}"; do
    gio mime "${type}" "${KAMI_ENTRY}" >/dev/null
done
echo "Set Kami as the default for ${#KAMI_TYPES[@]} MIME types"

# KDE caches associations in sycoca; rebuild it, as xdg-mime does.
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 >/dev/null 2>&1 || true
fi

if [[ "${KAMI_ENTRY}" == kami.desktop ]]; then
    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *) echo "Note: ${BIN_DIR} isn't on PATH, so the kami command won't resolve (the desktop entry doesn't need it)." ;;
    esac

    echo
    echo "Done. Type kami in a terminal, or open a .txt or .md file, to start Kami."
else
    echo
    echo "Done. Open a .txt or .md file to start Kami."
fi
