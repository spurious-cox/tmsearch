# TMsearch 1.7.0

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

where the date is when that version was last modified. The copy's own
modified time is when you restored it, so it sorts as new in Finder. Restoring
a folder sets that time on the folder itself; the files inside keep theirs.
The copy is an ordinary file you can edit, rename and delete: TMsearch removes
the write-protection Time Machine puts on everything in a backup.

## Install

    brew install --cask spurious-cox/tap/tmsearch

or download the disk image from the latest release and drag TMsearch to
Applications. The Homebrew install also adds the `tmsearch` command.

## Full Disk Access

macOS only lets an app read Time Machine backups if it has Full Disk Access.
Turn it on in **System Settings › Privacy & Security › Full Disk Access**:

- for **TMsearch**, to use it from Finder;
- for **Terminal** (or the terminal app you use), to use the `tmsearch` command.

Without it, TMsearch says so and, from Finder, offers to open that page.
After an update, if TMsearch is listed but still refused, remove it with **−**
and add it again.

## Using it from Finder

Open TMsearch. It asks for:

1. the **source folder**, where the file was. Type the path if the folder no
   longer exists;
2. the **destination folder** for the restored copy;
3. the **name**: part of a file name, which can include `*` and `?`.

It then asks how far to search:

- **This folder only**: the quickest;
- **This folder and its subfolders**: a few seconds more;
- **Deep Search**: subfolders in every backup, which also finds files in
  folders you have since deleted. It takes minutes.

It remembers your choice for next time, then lists the versions it found.
Pick one, or Command-click to pick several, and click Restore. The copies
are shown in Finder.

## Using it from the terminal

    tmsearch [folder] [name]
    tmsearch -r [folder] [name]     also search subfolders
    tmsearch -d [folder] [name]     Deep Search

Results are numbered; type a number to restore that version, or several
numbers and ranges, such as `1 3 5-7`, to restore more than one. With no arguments,
`tmsearch` asks for the folder and name, offering the last ones you used.
`tmsearch --help` also shows your Time Machine disk and how many backups it
holds.

The name is matched anywhere in a file name, without regard to case. `*`
stands for any run of characters and `?` for any one character, so
`state*farm` finds both `Statefarm_home.pdf` and `State Farm Claim.eml`.

### Quoting names

The shell reads the command line before TMsearch does, so quote any name that
contains `*`, `?` or a space:

    tmsearch -r ~/Documents 'state*farm'
    tmsearch -r ~/Documents "state farm"

Unquoted, zsh (the macOS default shell) treats `*` and `?` as wildcards for
files in the current folder, and usually stops with `no matches found`. A space
splits the name into two arguments. A plain name such as `statefarm` needs no
quotes.

In zsh you can skip quoting `*` and `?` by adding this line to `~/.zshrc` and
opening a new terminal window:

    alias tmsearch='noglob tmsearch'

`noglob` tells zsh to leave wildcards alone for this one command; `~` is still
expanded. Then this works as typed:

    tmsearch -r ~/Documents state*farm

A name with a space still needs quotes.

## Subfolders and Deep Search

A subfolder search finds where matching files are in your newest backup, then
collects every version of each one from all of your backups. It does not find
a file in a subfolder that had already been deleted by the time of your newest
backup.

Deep Search does: it goes through the folder and all its subfolders in every
backup. That takes minutes rather than seconds, and longer for a big folder.
Searching your whole disk either way is not practical; pick the folder the
file was in, or one a level or two above it.

## Requirements

macOS 11 or later, on Apple silicon or Intel. The Time Machine backup disk must
be connected, or for a network backup, mounted.

## License

MIT. Problems and suggestions: open an issue at
https://github.com/spurious-cox/tmsearch/issues
