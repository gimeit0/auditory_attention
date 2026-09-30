import hashlib
import importlib
import importlib.util
from pathlib import Path
import py_compile
import sys
import tempfile
import unittest
from unittest.mock import patch
from snapshot_source_import import source_only_imports

class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.name='e0_cache_fixture'
        sys.path.insert(0,str(self.root)); self.addCleanup(sys.path.remove,str(self.root))
        self.addCleanup(sys.modules.pop,self.name,None)
        self.source=self.root/(self.name+'.py')

    def write(self,raw=b'VALUE = "source"\n'):
        self.source.write_bytes(raw)
        return {self.source.name:hashlib.sha256(raw).hexdigest()}

    def read(self,path,expected):
        self.assertEqual(path.suffix,'.py')
        return path.read_bytes()

    def test_valid_but_wrong_cache_never_read_or_modified(self):
        self.write(b'VALUE = "cached"\n')
        py_compile.compile(str(self.source),doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        cache=Path(importlib.util.cache_from_source(str(self.source)))
        before=cache.read_bytes()
        hashes=self.write()
        # Control proves the cache is accepted by the ordinary loader.
        self.assertEqual(importlib.import_module(self.name).VALUE,'cached')
        sys.modules.pop(self.name)
        with source_only_imports(self.root,hashes,self.read):
            self.assertEqual(importlib.import_module(self.name).VALUE,'source')
        self.assertEqual(cache.read_bytes(),before)

    def test_corrupt_cache_ignored(self):
        hashes=self.write()
        cache=Path(importlib.util.cache_from_source(str(self.source)))
        cache.parent.mkdir(); cache.write_bytes(b'bad cached code')
        with source_only_imports(self.root,hashes,self.read):
            self.assertEqual(importlib.import_module(self.name).VALUE,'source')
        self.assertEqual(cache.read_bytes(),b'bad cached code')

    def test_no_new_cache_even_if_write_enabled(self):
        hashes=self.write()
        with patch.object(sys,'dont_write_bytecode',False),source_only_imports(self.root,hashes,self.read):
            importlib.import_module(self.name)
        self.assertEqual(list(self.root.rglob('*.pyc')),[])

    def test_source_mutation_rejected_at_import(self):
        hashes=self.write()
        self.write(b'VALUE = "changed"\n')
        with source_only_imports(self.root,hashes,self.read):
            with self.assertRaisesRegex(ImportError,'SOURCE_SHA'): importlib.import_module(self.name)

    def test_unpinned_source_rejected(self):
        self.write()
        with source_only_imports(self.root,{},self.read):
            with self.assertRaisesRegex(ImportError,'UNPINNED'): importlib.import_module(self.name)

    def test_legacy_sourceless_cache_rejected(self):
        self.write()
        py_compile.compile(str(self.source),cfile=str(self.root/(self.name+'.pyc')),doraise=True)
        self.source.unlink(); importlib.invalidate_caches()
        with source_only_imports(self.root,{},self.read):
            with self.assertRaisesRegex(ImportError,'SOURCE_REQUIRED'): importlib.import_module(self.name)

    def test_exception_restores_meta_path(self):
        before=list(sys.meta_path)
        with self.assertRaises(RuntimeError):
            with source_only_imports(self.root,{},self.read): raise RuntimeError('failure')
        self.assertEqual(sys.meta_path,before)

    def test_nested_contexts_restore_correctly(self):
        before=list(sys.meta_path)
        with source_only_imports(self.root,{},self.read) as outer:
            with source_only_imports(self.root,{},self.read): pass
            self.assertIs(sys.meta_path[0],outer)
        self.assertEqual(sys.meta_path,before)

    def test_namespace_package_child_from_source(self):
        package=self.root/self.name
        package.mkdir()
        child=package/'child.py'
        raw=b'VALUE = 27\n'; child.write_bytes(raw)
        fullname=self.name+'.child'
        self.addCleanup(sys.modules.pop,fullname,None)
        with source_only_imports(self.root,{self.name+'/child.py':hashlib.sha256(raw).hexdigest()},self.read):
            self.assertEqual(importlib.import_module(fullname).VALUE,27)
        self.assertEqual(list(self.root.rglob('*.pyc')),[])

if __name__=='__main__': unittest.main()
