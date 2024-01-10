Folders we use:
- Requires a read only romfs (really just AI+Logic+Sequence, Pack, and RSDB for determining version)
- "appvar" has a subfolder for each romfs version you open. These contain a large cache.db which is rebuilt if deleted, and a modfs-specific history.db is planned. These are sqlite files, many tools will open them and a crude sql shell is included in-app.
- Output folder should be set to a mod romfs. Upon saving: Newly modified packs will be initialized from romfs, existing packs will have their dirty ainb files updated. This means we shouldn't clobber your mod's non-ainb changes.


Usage + dependencies:
```sh
# Quick start with default paths in repo: ROMFS=./romfs, APPVAR=./var, OUTPUT_MODFS=./var/modfs
pip install dearpygui mmh3 pyyaml byml sarc zstandard
python ainb_offline.py

# Or specify paths, eg write to emulator mod path
pip install dearpygui mmh3 pyyaml byml sarc zstandard orjson
ROMFS=~/totk100/romfs APPVAR=~/totk100/appcache OUTPUT_MODFS=~/appdata/Ryujinx/sdcard/atmosphere/contents/0100f2c0115b6000/romfs python ainb_offline.py

# Open given ainb, including any changes from modfs
# These are equivalent:
python3 ainb_offline.py AI/Assassin_Senior.action.interuptlargedamage.module.ainb  # romfs-relative
python3 ainb_offline.py romfs/AI/Assassin_Senior.action.interuptlargedamage.module.ainb  # cwd-relative into "romfs"
python3 ainb_offline.py Root:AI/Assassin_Senior.action.interuptlargedamage.module.ainb  # "Root" is a pack
# Or open from within packs, these are equivalent:
python3 ainb_offline.py Pack/Actor/Animal_Donkey_B.pack.zs:AI/NoMoveDonkey.root.ainb  # romfs-relative pack
python3 ainb_offline.py romfs/Pack/Actor/Animal_Donkey_B.pack.zs:AI/NoMoveDonkey.root.ainb  # cwd-relative pack

# By default romfs RSDB is checked to determine version, unless version is specified:
TITLE_VERSION=TOTK_100 python3 ainb_offline.py
```

Major limitations + known issues:
- userdefined param type edits have not been tested
- Missing: add/remove params, add/remove nodes, add/remove links
- Missing: attachments, all things exb
- Many links may be missing or wrong. This is a display issue, it doesn't affect serialization
- Many nodes don't get proper layout on the graph, and layout is generally bad. Purely visual
- Some files may crash, usually due to layout hitting a loop


Minor limitations + UX issues:
- Missing: Undo/history. We're tracking edit operations, but not persisting/restoring/presenting any undo yet
- Missing: Decent dirty state management (eg dirty indicators, autosave/confirmation, ...)


Problems? Please report *exactly* what you've attempted:
- What you've done to prepare python+pip and install dependencies
- How you started the program
- Where all relevant files are located
- What file you wanted to edit
- The contents of any error messages along the way
- Usually inspecting all of these things carefully will reveal what went wrong :)


Top dawgs
- Special thanks to dt12345 for their ainb parser+serializer: https://github.com/dt-12345/ainb
- Special thanks to dt12345 for their asb parser+serializer: https://github.com/dt-12345/asb
- Special thanks to Watertoon for their help reversing ainb
