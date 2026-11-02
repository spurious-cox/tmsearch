# TMsearch 1.3.0

Find every past version of a file in your Time Machine backups and restore the
one you want, without browsing backups one at a time in the Time Machine
interface.

Browsing in Time Machine is painfully slow: each step back through the
backups redraws the Finder window, and finding the right version of one file
can take many minutes. TMsearch searches every backup at once and has the full
list ready in seconds.

You give it the folder the file was in, and it lists each distinct version it
finds, newest first, with its modification date, size and
how many backups hold it. Files, folders and apps all work, including ones that
have since been deleted.

A restored copy is saved under a new name and never overwrites anything:

    <name>-<yyyymmdd-hhmmss>.<ext>

where the date is when that version was last modified.

## Install

    brew install --cask spurious-cox/tap/tmsearch

or download the disk image from the latest release and drag TMsearch to
Applications. The Homebrew install also adds the `tmsearch` command.

## Full Disk Access

macOS only lets an app read Time Machine backups if it has Full Disk Access.
Turn it on in **System Settings › Privacy & Security › Full Disk Access**:

- for **TMsearch**, to use it from Finder;
- for **Terminal** (or the terminal app you use), to use the `tmsearch` command.

Without it, TMsearch reports that it found no backups.

## Using it from Finder

Open TMsearch. It asks for:

1. the **source folder**, where the file was. Type the path if the folder no
   longer exists;
2. the **destination folder** for the restored copy;
3. the **name**: part of a file name, or a pattern such as `*.txt`.

Click **Search** to look in that folder, or **Search Subfolders** to look in
the folders inside it as well. It then lists the versions it found. Pick one and click Restore, and the copy
is shown in Finder.

## Using it from the terminal

    tmsearch [folder] [name]
    tmsearch -r [folder] [name]     also search subfolders

Results are numbered; type a number to restore that version. With no arguments,
`tmsearch` asks for the folder and name, offering the last ones you used.
`tmsearch --help` also shows your Time Machine disk and how many backups it
holds.

The name is matched without regard to case. A plain word matches anywhere in a
file name; `*` and `?` make it a pattern.

## Searching subfolders

A subfolder search finds where matching files are in your newest backup, then
collects every version of each one from all of your backups. A file that was
in a subfolder but had already been deleted by the time of your newest backup
is not found; search the folder it was directly in instead. Subfolder searches
of a large folder take longer, and searching your whole disk is not practical.

## Requirements

macOS 11 or later, on Apple silicon or Intel. The Time Machine backup disk must
be connected, or for a network backup, mounted.

## License

MIT. Problems and suggestions: open an issue at
https://github.com/spurious-cox/tmsearch/issues
