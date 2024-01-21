from __future__ import annotations
from dataclasses import dataclass, field
from typing import *

WILDCARD_ARRAY = '*'
WILDCARD_OBJECT = '**'

JSONPathSegment = Union[int, str]

@dataclass
class JSONPath:
    # Required list of path segments
    path: List[JSONPathSegment] = field(default_factory=list)
    # Optional aliases for path[i] indexes. Useful to eg yank node_i back out of a path
    names: Dict[str, int] = field(default_factory=dict)

    def segment_by_name(self, name: str) -> JSONPathSegment:
        return self.path[self.names[name]]

    def copy(self) -> JSONPath:
        return JSONPath(path=self.path.copy(), names=self.names.copy())

    @classmethod
    def _search_recurse(cls, json, path: List[JSONPathSegment], parent_path: List[JSONPathSegment]) -> List[JSONPath]:
        if len(path) == 0:  # leaf of search
            return [cls(path=parent_path)]

        matches = []
        for segment in path:
            if segment == WILDCARD_ARRAY:
                r = []
                if isinstance(json, list):
                    for i in range(len(json)):
                        r.extend(cls._search_recurse(json[i], path[1:], parent_path + [i]))
                return r
            elif segment == WILDCARD_OBJECT:
                r = []
                if isinstance(json, dict):
                    for k, v in json.items():
                        r.extend(cls._search_recurse(v, path[1:], parent_path + [k]))
                return r
            elif isinstance(segment, int):
                if not isinstance(json, list):
                    return []
                try:
                    return cls._search_recurse(json[segment], path[1:], parent_path + [segment])
                except IndexError:
                    return []
            elif isinstance(segment, str):
                if not isinstance(json, dict):
                    return []
                try:
                    return cls._search_recurse(json[segment], path[1:], parent_path + [segment])
                except KeyError:
                    return []
            else:
                raise ValueError(f"invalid path segment {segment}")
        return matches

    def glob(self, json) -> List[JSONPath]:
        # Expand wildcards to concrete keys+indexes in given json
        paths = self._search_recurse(json, self.path, [])
        for p in paths:
            p.names = self.names  # XXX .copy()? this is set by reference
        return paths

    def glob_one(self, json) -> Optional[JSONPath]:
        # *_one resolves globs to the first match
        paths = self.glob(json)
        return paths[0] if paths else None

    def get_one(self, json):
        if any(s in [WILDCARD_ARRAY, WILDCARD_OBJECT] for s in self.path):
            path = self.glob_one(json).path
        else:
            path = self.path

        out = json
        for s in path:
            out = out[s]
        return out

    def update_one(self, json, value):
        # update not create -- the index must exist for arrays, or obj/dict must exist
        if any(s in [WILDCARD_ARRAY, WILDCARD_OBJECT] for s in self.path):
            path = self.glob_one(json).path
        else:
            path = self.path

        objpath, key = path[:-1], path[-1]
        for s in objpath:
            json = json[s]
        json[key] = value


def test():
    data = {'foo': {'bar': 42, 'car': 69}, 'woo': {'bar': 43}}

    # Glob to all {} at a specified depth
    paths = JSONPath(['**', '**']).glob(data)
    vals = {p.get_one(data) for p in paths}
    assert vals == {42, 43, 69}

    # Get all the {} keys at a given depth
    paths = JSONPath(['**', '**'], {'oos': 0, 'ars': 1}).glob(data)
    vals = {p.segment_by_name('ars') for p in paths}
    assert vals == {'bar', 'car'}

    # Fetch values at matching paths
    oobars = JSONPath(['**', 'bar']).glob(data)
    vals = {p.get_one(data) for p in oobars}
    assert vals == {42, 43}

    data = [[0, {'foo': [420]}], [0, {'woo': ['blazeit']}]]

    # Arrays
    paths = JSONPath(['*', 1, '**', 0]).glob(data)
    vals = {p.get_one(data) for p in paths}
    assert vals == {420, 'blazeit'}

    # Mutate data
    JSONPath(['*', '*', 'woo', 0]).update_one(data, 69)
    vals = {p.get_one(data) for p in paths}
    assert vals == {420, 69}  # existing path resolves to updated value
