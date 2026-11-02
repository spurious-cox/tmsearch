#!/usr/bin/python3
"""
TMsearch - find and restore past versions of a file from Time Machine backups.
Version: 1.2.0

    Terminal:       tmsearch [directory] [name]     numbered results in the same window
    Finder:         double-click TMsearch.app       dialogs + numbered list window

    name is part of a file name (case-insensitive) or a pattern with * and ?.
    A restored copy is named  <name>-<yyyymmdd-hhmmss modified>.<ext>
    and never overwrites anything.

Needs Full Disk Access for Terminal (CLI) or TMsearch.app (double-click).

v1.2.0: one version number for the app and the script; preferences live
under com.timmccoy.tmsearch; the progress message no longer promises a time.
"""

import fnmatch
import os
import plistlib
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

MAX_GUI = 300
APP_VERSION = "1.2.0"
PREFS = os.path.expanduser("~/Library/Preferences/com.timmccoy.tmsearch.plist")


def load_prefs():
    """The last/current search: directory, pattern, destination, status, times."""
    try:
        with open(PREFS, "rb") as fh:
            return plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}


def save_prefs(**changes):
    prefs = load_prefs()
    prefs.update(changes)
    prefs["updated"] = datetime.now()
    try:
        with open(PREFS, "wb") as fh:
            plistlib.dump(prefs, fh)
    except OSError:
        pass


def tm_volume():
    """Lines describing the Time Machine volume, for --help."""
    r = subprocess.run(["/usr/bin/tmutil", "destinationinfo"], capture_output=True, text=True)
    info = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info.setdefault(k.strip(), v.strip())
    if not info:
        return ["  (no Time Machine destination found: %s)" % (r.stderr.strip() or "none configured")]
    mount = info.get("Mount Point", "")
    out = ["  Name:        %s" % info.get("Name", "?"),
           "  Kind:        %s" % info.get("Kind", "?"),
           "  Mounted at:  %s%s" % (mount or "?", "" if os.path.ismount(mount) else "  (NOT mounted)")]
    if info.get("Quota"):
        out.append("  Quota:       %s" % info["Quota"])
    if os.path.ismount(mount):
        st = os.statvfs(mount)
        out.append("  Disk:        %s free of %s" % (human(st.f_bavail * st.f_frsize),
                                                       human(st.f_blocks * st.f_frsize)))
    b = subprocess.run(["/usr/bin/tmutil", "listbackups"], capture_output=True, text=True)
    names = [os.path.basename(l).replace(".backup", "") for l in b.stdout.splitlines() if l.strip()]
    if names:
        out.append("  Backups:     %d, from %s to %s" % (len(names), names[0], names[-1]))
    else:
        out.append("  Backups:     none readable (%s)" % (b.stderr.strip().split(".")[0] or "none"))
    return out


def help_text():
    prefs = load_prefs()
    last = ["  (no search yet)"]
    if prefs.get("directory"):
        last = ["  Directory:    %s" % prefs["directory"],
                "  Pattern:      %s" % prefs.get("pattern", ""),
                "  Status:       %s" % prefs.get("status", ""),
                "  Destination:  %s" % prefs.get("destination", "(none yet)"),
                "  Restored:     %s" % prefs.get("restored", "(nothing yet)"),
                "  Updated:      %s" % prefs.get("updated", "")]
    return "\n".join(
        ["TMsearch %s - find and restore past versions of a file from Time Machine" % APP_VERSION, "",
         "USAGE",
         "  tmsearch [directory] [name]     terminal: numbered results in this window",
         "  tmsearch                        asks for them, offering the last ones as defaults",
         "  double-click TMsearch.app       dialogs: source folder, destination folder, name,",
         "                                  then a numbered list window to pick the one to restore",
         "  tmsearch -h | -help | --help    this text", "",
         "  name is part of a file name (case-insensitive) or a pattern with * and ?.",
         "  Folders and apps work too, and so do files that have since been deleted.",
         "  A restored copy is named <name>-<yyyymmdd-hhmmss modified>.<ext>",
         "  and never overwrites anything.", "",
         "LAST / CURRENT SEARCH (offered as the defaults next time)", "  " + PREFS] + last +
        ["", "TIME MACHINE VOLUME"] + tm_volume() +
        ["", "Needs Full Disk Access for Terminal (CLI) or TMsearch.app (double-click)."]) + "\n"


def die(msg, gui):
    if gui:
        osa('on run argv\ntell current application to activate\n'
            'display dialog (item 1 of argv) with title "TMsearch" buttons {"OK"} '
            'default button 1 with icon stop\nend run', [msg], report=False)
    else:
        sys.stderr.write("TMsearch: %s\n" % msg)
    sys.exit(1)


def osa(script, args=(), report=True):
    """Run AppleScript; return (returncode, stdout). Cancel is rc 1; any other failure is shown."""
    r = subprocess.run(["/usr/bin/osascript", "-e", script] + list(args),
                       capture_output=True, text=True)
    if r.returncode and "-128" not in r.stderr and report:
        die("AppleScript failed: %s" % r.stderr.strip(), True)
    return r.returncode, r.stdout.strip()


# ---------- scanning ----------

def list_backups(gui):
    r = subprocess.run(["/usr/bin/tmutil", "listbackups"], capture_output=True, text=True)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        die("No Time Machine backups found (%s). Is the backup disk connected, and does "
            "%s have Full Disk Access?" % (r.stderr.strip() or "none listed",
                                          "TMsearch.app" if gui else "Terminal"), gui)
    return out


def match_fn(pattern):
    p = pattern.lower()
    if any(c in p for c in "*?["):
        return lambda n: fnmatch.fnmatch(n.lower(), p)
    return lambda n: p in n.lower()


def scan_one(backup, directory, match):
    stamp = os.path.basename(backup).replace(".backup", "")
    for root in (os.path.join(backup, "Data"), backup):
        base = root + directory
        if os.path.isdir(base):
            break
    else:
        return []
    rows = []
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for n in names:
        if match(n):
            p = os.path.join(base, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            rows.append((n, int(st.st_mtime), st.st_size, os.path.isdir(p), p, stamp))
    return rows


def scan(directory, pattern, backups):
    """Return distinct versions, grouped by name, newest first."""
    match = match_fn(pattern)
    versions = {}
    with ThreadPoolExecutor(16) as ex:
        for rows in ex.map(lambda b: scan_one(b, directory, match), backups):
            for n, mtime, size, isdir, p, stamp in rows:
                v = versions.setdefault((n, mtime, size), {
                    "name": n, "mtime": mtime, "size": size, "dir": isdir,
                    "path": p, "last": stamp, "count": 0})
                v["count"] += 1
                if stamp >= v["last"]:
                    v["last"], v["path"] = stamp, p
    return sorted(versions.values(), key=lambda v: (v["name"].lower(), -v["mtime"]))


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def label(i, v):
    return "%d. %s%s  |  modified %s  |  %s  |  in %d backup%s, latest %s" % (
        i, v["name"], "/" if v["dir"] else "",
        datetime.fromtimestamp(v["mtime"]).strftime("%Y-%m-%d %H:%M:%S"),
        "folder" if v["dir"] else human(v["size"]), v["count"],
        "" if v["count"] == 1 else "s", v["last"])


# ---------- restoring ----------

def restore(v, dest_dir):
    stem, ext = os.path.splitext(v["name"])      # keeps .app etc. so the copy still opens
    when = datetime.fromtimestamp(v["mtime"]).strftime("%Y%m%d-%H%M%S")
    target = os.path.join(dest_dir, "%s-%s%s" % (stem, when, ext))
    k = 1
    while os.path.exists(target):
        k += 1
        target = os.path.join(dest_dir, "%s-%s-%d%s" % (stem, when, k, ext))
    # cp, not ditto: ditto fails on the protected com.apple.provenance attribute
    r = subprocess.run(["/bin/cp", "-Rp", v["path"], target], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "cp failed")
    return target


# ---------- terminal ----------

def cli(args):
    t0 = time.time()
    prefs = load_prefs()
    last_dir = prefs.get("directory") or os.getcwd()
    directory = args[0] if args else input("Source directory [%s]: " % last_dir).strip()
    directory = os.path.abspath(os.path.expanduser(directory or last_dir))
    last_pat = prefs.get("pattern", "")
    pattern = args[1] if len(args) > 1 else input(
        "File name (part of name, or pattern like *.pl)%s: " % (" [%s]" % last_pat if last_pat else "")).strip()
    pattern = pattern or last_pat
    if not pattern:
        return 0
    save_prefs(directory=directory, pattern=pattern, status="searching")
    backups = list_backups(False)
    results = scan(directory, pattern, backups)
    save_prefs(status="searched: %d version(s)" % len(results))
    print("\nScanned %d backups in %.1fs; %d version(s) of '%s' in %s\n" % (
        len(backups), time.time() - t0, len(results), pattern, directory))
    if not results:
        return 0
    for i, v in enumerate(results, 1):
        print(label(i, v))
    try:
        pick = input("\nNumber to restore (blank to quit): ").strip()
        if not pick:
            return 0
        v = results[int(pick) - 1]
        default_dest = prefs.get("destination") or directory
        dest = input("Restore into directory [%s]: " % default_dest).strip()
        dest = os.path.abspath(os.path.expanduser(dest or default_dest))
    except (ValueError, IndexError):
        sys.stderr.write("TMsearch: not a valid number\n")
        return 1
    except (EOFError, KeyboardInterrupt):
        return 0
    if not os.path.isdir(dest):
        sys.stderr.write("TMsearch: %s is not a directory\n" % dest)
        return 1
    target = restore(v, dest)
    save_prefs(destination=dest, restored=target, status="restored")
    print("Restored: %s" % target)
    return 0


# ---------- Finder / GUI ----------

def gui():
    prefs = load_prefs()
    ask = ('on run argv\ntell current application to activate\n'
           'set r to display dialog (item 1 of argv) default answer (item 2 of argv) '
           'with title "TMsearch" buttons (items 4 thru -1 of argv) default button (item 3 of argv)\n'
           'return (button returned of r) & "|" & (text returned of r)\nend run')

    def ask_folder(prompt, default, must_exist):
        """Typed path (so a folder deleted since need not exist) with a Browse... button."""
        path = default
        while True:
            rc, out = osa(ask, [prompt, path, "OK", "Cancel", "Browse...", "OK"])
            if rc:
                return None
            button, _, typed = out.partition("|")
            path = os.path.expanduser(typed.strip()) or path
            if button != "Browse...":
                path = os.path.abspath(path)
                if must_exist and not os.path.isdir(path):
                    osa('on run argv\ntell current application to activate\n'
                        'display dialog (item 1 of argv) with title "TMsearch" buttons {"OK"} '
                        'default button 1 with icon caution\nend run',
                        ["%s is not a folder." % path])
                    continue
                return path
            start = path
            while start != "/" and not os.path.isdir(start):
                start = os.path.dirname(start) or "/"
            rc, chosen = osa('on run argv\ntell current application to activate\n'
                             'return POSIX path of (choose folder with prompt "TMsearch: choose the folder" '
                             'default location (POSIX file (item 1 of argv)))\nend run', [start])
            if not rc and chosen:
                path = chosen

    # 1. source: where the file was. It is typed, so a folder that no longer exists works.
    directory = ask_folder("SOURCE folder: where the file was when it last existed.\n"
                           "Type a path or click Browse (it need not exist now).",
                           prefs.get("directory") or os.path.expanduser("~"), False)
    if not directory:
        return 0
    # 2. destination: where the recovered copy will go
    dest = ask_folder("DESTINATION folder for the recovered copy.\nType a path or click Browse.",
                      prefs.get("destination") or directory, True)
    if not dest:
        return 0
    # 3. the pattern, last
    rc, out = osa(ask, ["File name to recover (part of a name, or a pattern like *.pl):\nsearching in "
                        + directory, prefs.get("pattern", ""), "Search", "Cancel", "Search"])
    pattern = out.split("|", 1)[-1].strip()
    if rc or not pattern:
        return 0
    save_prefs(directory=directory, pattern=pattern, destination=dest, status="searching")
    dlg = subprocess.Popen(
        ["/usr/bin/osascript", "-e",
         'on run argv\ntell current application to activate\n'
         'display dialog (item 1 of argv) with title "TMsearch" buttons {"Cancel"} '
         'default button 1 with icon note giving up after 900\nend run',
         "Searching Time Machine backups for '%s'\nin %s\n\nThe more backups there are, the longer this takes."
         % (pattern, directory)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    found = []
    worker = threading.Thread(target=lambda: found.append(
        scan(directory, pattern, list_backups(True))), daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(0.2)
        if dlg.poll() is not None:        # Cancel clicked
            os._exit(0)
    dlg.terminate()
    if not found:
        return 1
    results = found[0]
    backups = ()
    save_prefs(status="searched: %d version(s)" % len(results))
    if not results:
        die("No versions of '%s' found in %s." % (pattern, directory), True)
    shown = results[:MAX_GUI]
    note = " (first %d of %d)" % (MAX_GUI, len(results)) if len(results) > MAX_GUI else ""
    rc, choice = osa('on run argv\ntell current application to activate\n'
                     'set r to choose from list (items 2 thru -1 of argv) with title "TMsearch" '
                     'with prompt (item 1 of argv) OK button name "Restore" cancel button name "Cancel"\n'
                     'if r is false then error number -128\nreturn item 1 of r\nend run',
                     ["Pick ONE result to restore%s:" % note] + [label(i, v) for i, v in enumerate(shown, 1)])
    if rc or not choice:
        return 0
    v = shown[int(choice.split(".", 1)[0]) - 1]
    try:
        target = restore(v, dest)
    except RuntimeError as e:
        die("Restore failed: %s" % e, True)
    save_prefs(restored=target, status="restored")
    subprocess.run(["/usr/bin/open", "-R", target])
    osa('on run argv\ntell current application to activate\n'
        'display dialog ("Restored to:\n" & item 1 of argv) with title "TMsearch" '
        'buttons {"OK"} default button 1\nend run', [target])
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    if any(a in ("-h", "-help", "--help") for a in args):
        text = help_text()
        if "--gui" not in args and (sys.stdin.isatty() or "--cli" in args or os.environ.get("TERM")):
            sys.stdout.write(text)
        else:
            osa('on run argv\ntell current application to activate\n'
                'display dialog (item 1 of argv) with title "TMsearch help" buttons {"OK"} '
                'default button 1\nend run', [text])
        return 0
    if "--gui" in args or ("--cli" not in args and not sys.stdin.isatty()):
        return gui()
    return cli([a for a in args if a not in ("--cli", "--gui")])


if __name__ == "__main__":
    sys.exit(main())
