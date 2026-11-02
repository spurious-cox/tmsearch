#!/usr/bin/python3
"""
TMsearch - find and restore past versions of a file from Time Machine backups.
Version: 1.6.1

    Terminal:       tmsearch [-r|-d] [directory] [name]   numbered results in the same window
    Finder:         double-click TMsearch.app       dialogs + numbered list window

    name is part of a file name (case-insensitive), optionally with * and ?.
    A restored copy is named  <name>-<yyyymmdd-hhmmss modified>.<ext>
    and never overwrites anything.

Needs Full Disk Access for Terminal (CLI) or TMsearch.app (double-click).

v1.2.0: one version number for the app and the script; preferences live
under com.timmccoy.tmsearch; the progress message no longer promises a time.

v1.3.0: subfolder search (-r, or Search Subfolders in Finder). The newest
backup that holds the folder is walked to find where matching files live, and
each of those paths is then looked up in every backup. A file deleted before
that newest backup is only found if it was directly in the folder searched.

v1.4.0: Deep Search (-d, or Deep Search in Finder) walks the folder and its
subfolders in every backup, so it also finds files in folders since deleted.
It takes minutes rather than seconds. In Finder the search scope is chosen
from a list after the name, since a dialog holds only three buttons.

v1.5.0: a pattern with * or ? matches anywhere in a name, as a plain word
does. A folder that is in none of the backups is reported as such instead of
as 0 versions. The terminal prompts have line editing, and Control-C ends
the line before quitting.

v1.5.1: --help explains quoting names in the shell.

v1.6.0: a restored copy's modified time is the time it was restored; its name
still carries the version's own modified time. The copy also loses the access
rule Time Machine puts on every backed-up item (everyone: deny write, delete,
writeattr ...), which cp -p carried over and which left restored files
impossible to edit or delete normally.

v1.6.1: missing Full Disk Access gets its own message naming the app that
needs it, with an Open Settings button in Finder, instead of tmutil's text,
which always says to add Terminal.
"""

import fnmatch
import os
import plistlib
try:
    import readline                     # arrow keys and editing at input() prompts
except ImportError:
    pass
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

MAX_GUI = 300
# Search scopes, as offered in Finder, in order.
SCOPES = ("This folder only",
          "This folder and its subfolders",
          "Deep Search: every backup, also finds deleted folders (takes minutes)")
SCOPE_MODES = ("folder", "subfolders", "deep")
APP_VERSION = "1.6.1"
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
         "  tmsearch -r [directory] [name]  also search subfolders",
         "  tmsearch -d [directory] [name]  Deep Search: subfolders in every backup (minutes)",
         "  tmsearch                        asks for them, offering the last ones as defaults",
         "  double-click TMsearch.app       dialogs: source folder, destination folder, name,",
         "                                  then a numbered list window to pick the one to restore",
         "  tmsearch -h | -help | --help    this text", "",
         "  name is part of a file name (case-insensitive), optionally with * and ?:",
         "  state*farm matches 'Statefarm_home.pdf' and 'State Farm Claim.eml'.",
         "",
         "  Quote a name that has *, ? or a space, or the shell changes it first:",
         "      tmsearch -r ~/Documents 'state*farm'",
         "      tmsearch -r ~/Documents \"state farm\"",
         "  In zsh, this alias in ~/.zshrc removes the need to quote * and ?:",
         "      alias tmsearch='noglob tmsearch'",
         "  Folders and apps work too, and so do files that have since been deleted.",
         "  -r finds matches in subfolders that exist in the newest backup holding the folder;",
         "  each one is then looked up in every backup.",
         "  -d walks the folder in every backup, so it also finds files in deleted folders.",
         "  A restored copy is named <name>-<yyyymmdd-hhmmss modified>.<ext>,",
         "  and its own modified time is when it was restored.",
         "  Restoring never overwrites anything.", "",
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

FDA_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


def no_disk_access(gui):
    """tmutil's own message always says to add Terminal, whoever is asking."""
    who = "TMsearch" if gui else "Terminal (or the terminal app you use)"
    msg = ("TMsearch needs Full Disk Access to read your Time Machine backups.\n\n"
           "In System Settings > Privacy & Security > Full Disk Access, click +, "
           "add %s, and turn it on." % who)
    if gui:
        msg += (" If TMsearch is already listed, remove it with - and add it again; "
                "an updated copy is not covered by the old entry.")
    if not gui:
        sys.stderr.write("TMsearch: %s\n" % msg.replace("\n\n", "\n"))
        sys.exit(1)
    rc, button = osa('on run argv\ntell current application to activate\n'
                     'return button returned of (display dialog (item 1 of argv) '
                     'with title "TMsearch" buttons {"OK", "Open Settings"} '
                     'default button 2 with icon stop)\nend run', [msg], report=False)
    if button == "Open Settings":
        subprocess.run(["/usr/bin/open", FDA_SETTINGS])
    sys.exit(1)


def list_backups(gui):
    r = subprocess.run(["/usr/bin/tmutil", "listbackups"], capture_output=True, text=True)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        if "Full Disk Access" in r.stderr:
            no_disk_access(gui)
        die("No Time Machine backups found. Is the backup disk connected?%s"
            % ("\n\n(%s)" % r.stderr.strip() if r.stderr.strip() else ""), gui)
    return out


def match_fn(pattern):
    """Case-insensitive, and anywhere in the name, with or without * and ?."""
    p = pattern.lower()
    if any(c in p for c in "*?["):
        p = ("" if p.startswith("*") else "*") + p + ("" if p.endswith("*") else "*")
        return lambda n: fnmatch.fnmatch(n.lower(), p)
    return lambda n: p in n.lower()


def in_any_backup(directory, backups):
    return any(backup_base(b, directory) for b in backups)


def backup_base(backup, directory):
    """Where `directory` is inside one backup, or None if it is not there."""
    for root in (os.path.join(backup, "Data"), backup):
        base = root + directory
        if os.path.isdir(base):
            return base
    return None


def find_subpaths(directory, match, backups):
    """Matching paths below the folder's top level, relative to it.

    Walks only the newest backup that holds the folder: walking every backup
    takes minutes for a large folder, and the per-backup lookups in scan_one
    then find every version of each path that turns up here.
    """
    for backup in reversed(backups):
        base = backup_base(backup, directory)
        if base:
            break
    else:
        return []
    found = []
    for root, dirs, files in os.walk(base):
        if root == base:
            continue                    # the top level is scanned in every backup anyway
        for n in dirs + files:
            if match(n):
                found.append(os.path.relpath(os.path.join(root, n), base))
    return found


def scan_one(backup, directory, match, subpaths=(), deep=False):
    stamp = os.path.basename(backup).replace(".backup", "")
    base = backup_base(backup, directory)
    if base is None:
        return []
    rows = []
    if deep:
        for root, dirs, files in os.walk(base):
            for n in dirs + files:
                if match(n):
                    p = os.path.join(root, n)
                    try:
                        st = os.lstat(p)
                    except OSError:
                        continue
                    rows.append((os.path.relpath(p, base), int(st.st_mtime), st.st_size,
                                 os.path.isdir(p), p, stamp))
        return rows
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
    for rel in subpaths:
        p = os.path.join(base, rel)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        rows.append((rel, int(st.st_mtime), st.st_size, os.path.isdir(p), p, stamp))
    return rows


def scan(directory, pattern, backups, mode="folder", progress=None):
    """Return distinct versions, grouped by name, newest first.

    mode is "folder", "subfolders" or "deep". A name is relative to
    `directory`, so a match in a subfolder shows where it is. progress, if
    given, is called with (backups done, backups in all).
    """
    match = match_fn(pattern)
    subpaths = find_subpaths(directory, match, backups) if mode == "subfolders" else []
    deep = mode == "deep"
    versions = {}
    with ThreadPoolExecutor(16) as ex:
        for done, rows in enumerate(ex.map(
                lambda b: scan_one(b, directory, match, subpaths, deep), backups), 1):
            if progress:
                progress(done, len(backups))
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
    stem, ext = os.path.splitext(os.path.basename(v["name"]))   # keeps .app etc. so the copy still opens
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
    # -p also copied the deny-write/delete ACL Time Machine puts on every
    # backed-up item. Remove it throughout, or the copy cannot be edited,
    # renamed or deleted normally.
    r = subprocess.run(["/bin/chmod", "-R", "-N", target], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "could not clear the backup's access rule")
    # -p kept the backup's times; the copy is stamped with now so it sorts as
    # new. Only the top item: a restored folder's contents keep their own.
    os.utime(target, follow_symlinks=False)
    return target


# ---------- terminal ----------

def cli(args, mode="folder"):
    t0 = time.time()
    prefs = load_prefs()
    last_dir = prefs.get("directory") or os.getcwd()
    directory = args[0] if args else input("Source directory [%s]: " % last_dir).strip()
    directory = os.path.abspath(os.path.expanduser(directory or last_dir))
    last_pat = prefs.get("pattern", "")
    pattern = args[1] if len(args) > 1 else input(
        "File name (part of a name; * and ? allowed)%s: " % (" [%s]" % last_pat if last_pat else "")).strip()
    pattern = pattern or last_pat
    if not pattern:
        return 0
    save_prefs(directory=directory, pattern=pattern, status="searching")
    backups = list_backups(False)
    progress = None
    if mode == "deep":
        progress = lambda done, total: sys.stderr.write(
            "\rDeep Search: %d of %d backups%s" % (done, total, "\n" if done == total else ""))
    results = scan(directory, pattern, backups, mode, progress)
    save_prefs(status="searched: %d version(s)" % len(results))
    print("\nScanned %d backups in %.1fs; %d version(s) of '%s' in %s%s\n" % (
        len(backups), time.time() - t0, len(results), pattern, directory,
        {"folder": "", "subfolders": " and its subfolders",
         "deep": " and its subfolders (Deep Search)"}[mode]))
    if not results:
        if not in_any_backup(directory, backups):
            sys.stderr.write("TMsearch: %s is not in any of the backups. Check the folder's path.\n"
                             % directory)
            return 1
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
        print()
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
    rc, out = osa(ask, ["File name to recover (part of a name; * and ? allowed, as in state*farm):\nsearching in "
                        + directory, prefs.get("pattern", ""), "Search", "Cancel", "Search"])
    pattern = out.split("|", 1)[-1].strip()
    if rc or not pattern:
        return 0
    # 4. how far to look. The last choice is preselected.
    last = prefs.get("scope") if prefs.get("scope") in SCOPE_MODES else "folder"
    rc, out = osa('on run argv\ntell current application to activate\n'
                  'set r to choose from list (items 3 thru -1 of argv) with title "TMsearch" '
                  'with prompt (item 1 of argv) default items {item 2 of argv} '
                  'OK button name "Search" cancel button name "Cancel"\n'
                  'if r is false then error number -128\nreturn item 1 of r\nend run',
                  ["Search for '%s' in:" % pattern, SCOPES[SCOPE_MODES.index(last)]] + list(SCOPES))
    if rc or out not in SCOPES:
        return 0
    mode = SCOPE_MODES[SCOPES.index(out)]
    save_prefs(directory=directory, pattern=pattern, destination=dest, scope=mode,
               status="searching")
    dlg = subprocess.Popen(
        ["/usr/bin/osascript", "-e",
         'on run argv\ntell current application to activate\n'
         'display dialog (item 1 of argv) with title "TMsearch" buttons {"Cancel"} '
         'default button 1 with icon note\nend run',
         "Searching Time Machine backups for '%s'\nin %s%s\n\n%s"
         % (pattern, directory,
            {"folder": "", "subfolders": " and its subfolders",
             "deep": " and its subfolders, in every backup"}[mode],
            "Deep Search takes minutes; the bigger the folder, the longer."
            if mode == "deep" else "The more backups there are, the longer this takes.")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    found = []
    worker = threading.Thread(target=lambda: found.append(
        scan(directory, pattern, list_backups(True), mode)), daemon=True)
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
        if not in_any_backup(directory, list_backups(True)):
            die("%s is not in any of the backups. Check the folder's path." % directory, True)
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
    mode = "folder"
    if any(a in ("-r", "--subfolders") for a in args):
        mode = "subfolders"
    if any(a in ("-d", "--deep") for a in args):
        mode = "deep"
    flags = ("--cli", "--gui", "-r", "--subfolders", "-d", "--deep")
    try:
        return cli([a for a in args if a not in flags], mode)
    except KeyboardInterrupt:
        print()                         # end the ^C line so the shell prompt starts clean
        return 130


if __name__ == "__main__":
    sys.exit(main())
