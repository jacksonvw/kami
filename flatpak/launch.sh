#!/bin/sh
# Flatpak launcher, installed as /app/bin/kami.
#
# bin/kami logs to /tmp, which is private to the sandbox, so the host never
# sees it. This logs where the host can read it, e.g.
#   tail -n 200 ~/.var/app/com.jacksonv.Kami/cache/kami.log
# appended to, as the checkout's log is: a second kami hands its files to the
# running one and exits, and truncating the log would cut the running Kami's
# log out from under it.
#
# -P keeps the folder Kami was started in off sys.path. Kami can start from
# anywhere, and a logging.py there mustn't be imported in place of Python's.
export PYTHONPATH=/app/share/kami
exec python3 -P -m kami.main "$@" >>"$XDG_CACHE_HOME/kami.log" 2>&1
