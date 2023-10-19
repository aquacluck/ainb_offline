very wip, no support included :)

I need a romfs folder at `romfs`, you gotta put it there, yes you. You can also pass a single ainb file in argv, but that won't work as soon as we do anything recursive.

```sh
pip install dearpygui mmh3 pyyaml sarc zstandard
python main.py romfs/Sequence/AutoPlacement.root.ainb
```

dt_ainb adapted from https://github.com/dt-12345/ainb, other than relative imports any edits are mostly pointless

