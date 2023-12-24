Folders we use:
- Requires a read only romfs (really just AI, Logic, Sequence, Pack)
- "appvar" folder is for cache, history, etc
- Output folder should be set to a mod romfs. Upon saving: Newly modified packs will be initialized from romfs, existing packs will have their dirty ainb files updated. This means we shouldn't clobber your mod's non-ainb changes.

```sh
pip install dearpygui mmh3 pyyaml byml sarc zstandard
python src/main.py  # Default paths are in repo: ROMFS=./romfs, APPVAR=./var, OUTPUT_ROMFS=./var/modfs
ROMFS=~/totk100/romfs APPVAR=~/totk100/appcache OUTPUT_ROMFS=~/totk100/modfs python src/main.py  # Specify paths
```

- Special thanks to dt12345 for their ainb parser+serializer: https://github.com/dt-12345/ainb
- Special thanks to Watertoon for their help reversing the format
