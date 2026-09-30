"""Scoped source-only imports for an already hash-verified snapshot.

Compile the exact hash-checked source bytes; never ask a loader for cached code.
Does not modify global SourceFileLoader behavior or any snapshot/cache file.
"""
from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.machinery
from pathlib import Path
import sys

class SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def __init__(self,fullname,path,expected,read_bytes):
        super().__init__(fullname,str(path))
        self.expected=expected
        self.read_bytes=read_bytes

    def get_code(self,fullname):
        raw=self.read_bytes(Path(self.path),self.expected)
        if hashlib.sha256(raw).hexdigest()!=self.expected:
            raise ImportError('SNAPSHOT_SOURCE_SHA: '+self.path)
        return self.source_to_code(raw,self.path)

    def set_data(self,*args,**kwargs):
        raise ImportError('SNAPSHOT_CACHE_WRITE_FORBIDDEN')

class SnapshotSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self,root,hashes,read_bytes):
        self.root=Path(root).resolve()
        self.hashes=dict(hashes)
        self.read_bytes=read_bytes

    def find_spec(self,fullname,path=None,target=None):
        spec=importlib.machinery.PathFinder.find_spec(fullname,path,target)
        if spec is None: return None
        protected=fullname.split('.')[0] in ('src','selftrain')
        if spec.origin is None and spec.submodule_search_locations is not None:
            locations=[Path(p).resolve() for p in spec.submodule_search_locations]
            inside=[p.is_relative_to(self.root) for p in locations]
            if protected or any(inside):
                if not locations or not all(inside): raise ImportError('SNAPSHOT_NAMESPACE_ESCAPE')
                return spec
            return None
        if not spec.origin: return None
        source=Path(spec.origin)
        inside=source.resolve().is_relative_to(self.root)
        if not inside:
            if protected: raise ImportError('SNAPSHOT_IMPORT_ESCAPE: '+fullname)
            return None
        if source.suffix!='.py' or not isinstance(spec.loader,importlib.machinery.SourceFileLoader):
            raise ImportError('SNAPSHOT_SOURCE_REQUIRED: '+fullname)
        relative=str(source.resolve().relative_to(self.root))
        if relative not in self.hashes: raise ImportError('SNAPSHOT_UNPINNED_SOURCE: '+relative)
        spec.loader=SourceOnlyLoader(fullname,source,self.hashes[relative],self.read_bytes)
        return spec

@contextmanager
def source_only_imports(root,hashes,read_bytes):
    finder=SnapshotSourceFinder(root,hashes,read_bytes)
    sys.meta_path.insert(0,finder)
    try:
        yield finder
    finally:
        if finder in sys.meta_path: sys.meta_path.remove(finder)
