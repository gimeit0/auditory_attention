"""G2 bounded array storage and offline content verification; not a launcher.

No numeric imports at import/Consumer construction time. The live caller keeps
the original scopes open; the offline verifier only checks bytes, commitments
and the numeric decision. It does NOT authenticate execution or approve GPU use.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import types

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = HERE.parent / 'targeted_gpu_pair_20260915_scan/pass_archive.py'
SOURCE_SHA = '48fe6e50b54a1b5a2ab88057dcbc2be5bd073f00fae9c06eaf7273a61026dfbd'
GEOMETRY = ROOT / 'docs/superpowers/evidence/parent-replay-local-20260911T155226Z-rcw6ytm5/PARENT_REPLAY_CONTRACT.json'
GEOMETRY_SHA = '95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34'
PARENT = ROOT / 'docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json'
PARENT_SHA = 'bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178'
SHA = re.compile('[0-9a-f]{64}')
DTYPES = {'torch.float16':'<f2', 'torch.float32':'<f4', 'torch.float64':'<f8',
          'torch.int64':'<i8', 'torch.bool':'|b1', 'float16':'<f2', 'float32':'<f4',
          'float64':'<f8', 'int64':'<i8', 'bool':'|b1'}
META_KEYS = {'job_id', 'pid', 'profile', 'input_freeze_sha256', 'input_relation', 'preparation', 'scratch'}


def require(ok, message):
    if not ok: raise ValueError('G2 archive: ' + message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                       allow_nan=False) + '\n').encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(path, digest, limit=8 * 1024**2):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
            and path.stat().st_size <= limit, 'bounded nonsymlink source required')
    raw = path.read_bytes()
    require(sha(raw) == digest, 'source pin differs: ' + str(path))
    return raw


def binding_check(value):
    require(type(value) is dict and set(value) == {'job_id', 'pid', 'profile', 'role',
        'input_freeze_sha256', 'release_sha256', 'trial_identity_sha256',
        'metadata_sha256', 'trust_domain'}, 'binding schema differs')
    require(type(value['job_id']) is str and re.fullmatch('[1-9][0-9]{0,19}', value['job_id'])
            and type(value['pid']) is int and value['pid'] > 0
            and value['profile'] in ('R','C','D','E') and value['role'] == 'observed'
            and value['trust_domain'] in ('production','hermetic-test'), 'binding identity differs')
    require(all(type(value[k]) is str and SHA.fullmatch(value[k]) for k in
        ('input_freeze_sha256','release_sha256','trial_identity_sha256','metadata_sha256')),
        'binding digest differs')


def build_codec():
    """Reuse unchanged writer/stream reader. Only file cap and binding schema differ."""
    raw = pinned(SOURCE, SOURCE_SHA)
    geometry = json.loads(pinned(GEOMETRY, GEOMETRY_SHA))
    parts = list(geometry['cells']['B2']['passes'].values())
    sizes = [b['aggregate']['nbytes'] for p in parts for b in p['boundaries'].values()]
    total = sum(sizes) + sum(p['boundaries'][n]['aggregate']['nbytes']
                            for p in parts for n in ('nll','p_target','p_probe_distractor','pred_label'))
    require(max(sizes) == 204800000 and total <= 2 * 1024**3, 'fixed geometry budget differs')
    tree = ast.parse(raw)
    before = copy.deepcopy(tree)
    matches = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'MAX_ARRAY']
    require(len(matches) == 1 and ast.unparse(matches[0].value) == '128 * CHUNK', 'file cap source differs')
    old_cap = matches[0].value
    matches[0].value = ast.Constant(204800000)
    checks = [(i,n) for i,n in enumerate(tree.body) if isinstance(n,ast.FunctionDef) and n.name == 'binding_check']
    require(len(checks) == 1, 'binding source differs')
    index, old_check = checks[0]
    tree.body[index] = ast.parse('def binding_check(value):\n    return _g2_binding_check(value)\n').body[0]
    code = compile(ast.fix_missing_locations(tree), str(SOURCE), 'exec', dont_inherit=True)
    matches[0].value, tree.body[index] = old_cap, old_check
    require(ast.dump(tree) == ast.dump(before), 'unreviewed writer change')
    module = types.ModuleType('g2_bounded_archive_codec')
    module.__file__ = str(SOURCE)
    module._g2_binding_check = binding_check
    exec(code, vars(module))
    require(module.CHUNK == 1024**2 and module.MAX_TOTAL == 2*1024**3
            and module.MAX_JSON == 8*1024**2, 'other capacity changed')
    return module


def bind(metadata, trials, release_sha, trust_domain):
    require(type(metadata) is dict and set(metadata) == META_KEYS
            and len(canonical(metadata)) <= 512*1024, 'metadata schema/budget differs')
    value = {k:metadata[k] for k in ('job_id','pid','profile','input_freeze_sha256')}
    value.update(role='observed', release_sha256=release_sha, metadata_sha256=sha(canonical(metadata)),
                 trial_identity_sha256=sha(canonical(trials)), trust_domain=trust_domain)
    binding_check(value)
    return value


def check_trials(diag, binding, trials):
    diag._validate_trial_documents(trials)
    require(sha(canonical(trials)) == binding['trial_identity_sha256'], 'full trial identity differs')
    if binding['trust_domain'] == 'production':
        require(trials == json.loads(pinned(PARENT, PARENT_SHA))['trials'], 'production frozen trials differ')


class Consumer:
    """One-shot ProductionCell callback; partial artifacts remain on every failure."""
    def __init__(self, root, bridge, diag, *, binding, trials):
        binding_check(binding)
        self.root, self.bridge, self.diag = Path(root), bridge, diag
        self.binding, self.trials = json.loads(canonical(binding)), json.loads(canonical(trials))
        self.used = False

    def __call__(self, result, metadata):
        require(not self.used, 'consumer is single use')
        self.used = True
        bridge, diag = self.bridge, self.diag
        bridge._check_module(diag)
        require(self.binding == bind(metadata, self.trials, self.binding['release_sha256'], result['trust_domain'])
                and self.binding['pid'] == os.getpid() and result['profile'] == diag._G2_PROFILE
                == self.binding['profile'], 'live identity differs')
        check_trials(diag, self.binding, self.trials)
        require(result['trial_identity_sha256'] == self.binding['trial_identity_sha256']
                and result['status'] == ('G2_CELL_CANDIDATE_COMPLETE' if result['trust_domain'] == 'production'
                                         else 'HERMETIC_G2_CELL_COMPLETE'), 'cell scope differs')
        require(len(result['passes']) == 2, 'two passes required')
        summary = canonical({k:v for k,v in result.items() if k != 'passes'})
        commitments = [bridge._commitment(diag, p) for p in result['passes']]
        require(commitments == result['pass_commitments'], 'cell commitments differ')
        codec = build_codec()
        writer = codec.PassArchive(self.root, self.binding)
        try:
            for part in result['passes']:
                original = diag.encode_pass_evidence(part)
                arrays = {n:diag._cpu_artifact_array((part.boundary_records[n] if n in codec.COARSE
                            else part.boundary_records['derived'][n])['tensor'])
                          for n in codec.COARSE + codec.DERIVED}
                writer.capture_pass(part.pass_id, part.batch_size, list(part.trial_ids),
                                    arrays, dict(part.outputs), original)
                require(diag.encode_pass_evidence(part) == original, 'storage changed pass evidence')
            manifest = writer.finish()
        finally:
            writer.close()
        require(commitments == [bridge._commitment(diag,p) for p in result['passes']]
                and summary == canonical({k:v for k,v in result.items() if k != 'passes'}),
                'storage changed cell')
        receipt = dict(status='G2_PASS_ARTIFACTS_WRITTEN', **{k:metadata[k] for k in
                       ('job_id','pid','profile','input_freeze_sha256')}, binding=self.binding,
                       metadata=json.loads(canonical(metadata)), cell_summary=json.loads(summary),
                       pass_commitments=commitments, archive_manifest_sha256=manifest['sha256'],
                       archive_manifest_size=manifest['size'], independent_results_verified=False)
        require(len(canonical(receipt)) <= 1024**2, 'receipt budget exceeded')
        return receipt


def descriptor(record, *, scalar=False):
    require(type(record) is dict and record.get('dtype') in DTYPES, 'committed dtype differs')
    shape = record.get('shape')
    require(type(shape) is list and (bool(shape) or scalar), 'committed shape differs')
    return dict(dtype=DTYPES[record['dtype']], shape=shape or [1], nbytes=record['nbytes'], sha256=record['sha256'])


def numeric_summary(outputs):
    """Recompute only from rehashed official bytes, independent of the live bridge."""
    import numpy as np
    comparisons, accepted = {}, True
    for name in ('pred_label','nll','p_target','p_probe_distractor'):
        a,b = (p[name] for p in outputs)
        require(a.shape == b.shape == (32,) and a.dtype == b.dtype
                and a.dtype.kind in ('i' if name == 'pred_label' else 'f')
                and np.isfinite(a).all() and np.isfinite(b).all(), 'numeric shape/dtype/finite differs')
        if name == 'pred_label':
            require(bool(((a>=0)&(a<800)&(b>=0)&(b<800)).all()), 'label outside 800 classes')
            flips = int(np.count_nonzero(a != b))
            comparisons[name] = dict(flips=flips, exact=flips==0)
            accepted &= flips == 0
        else:
            delta = np.abs(a.astype(np.float64) - b.astype(np.float64))
            count = int(np.count_nonzero(delta > 1e-6))
            comparisons[name] = dict(max_abs=float(np.max(delta)), median_abs=float(np.median(delta)),
                p95_abs=float(np.quantile(delta,.95)), p99_abs=float(np.quantile(delta,.99)), above_atol=count)
            accepted &= count == 0
    return dict(status='NUMERIC_ACCEPT' if accepted else 'NUMERIC_DIFF', atol=1e-6,
                comparisons=comparisons, scientific_acceptance=False)


def verify(root, receipt, *, receipt_sha, expected_binding, trials, bridge, diag):
    """Read-only. Supervisor must independently pin receipt/binding/trials/source.

Original decoder checks serialized commitment self-consistency (not origin).
All forty arrays are streamed and compared to that commitment's aggregate and
32 row hashes; official bytes must also equal the original lossless encoding.
"""
    binding_check(expected_binding)
    bridge._check_module(diag)
    check_trials(diag, expected_binding, trials)
    require(len(canonical(receipt)) <= 1024**2 and sha(canonical(receipt)) == receipt_sha,
            'external receipt digest differs')
    require(set(receipt) == {'status','job_id','pid','profile','input_freeze_sha256','binding',
        'metadata','cell_summary','pass_commitments','archive_manifest_sha256','archive_manifest_size',
        'independent_results_verified'} and receipt['status'] == 'G2_PASS_ARTIFACTS_WRITTEN'
        and receipt['independent_results_verified'] is False, 'receipt schema/scope differs')
    require(receipt['binding'] == expected_binding == bind(receipt['metadata'], trials,
            expected_binding['release_sha256'], expected_binding['trust_domain'])
            and all(receipt[k] == expected_binding[k] for k in ('job_id','pid','profile','input_freeze_sha256'))
            and diag._G2_PROFILE == expected_binding['profile'], 'external receipt identity differs')
    codec = build_codec()
    size, digest = receipt['archive_manifest_size'], receipt['archive_manifest_sha256']
    require(type(size) is int and 0 < size <= codec.MAX_JSON, 'manifest size differs')
    fd = codec.directory(root)
    try:
        raw = b''.join(codec.chunks(fd,'manifest.json',size,digest))
        value = json.loads(raw)
        require(codec.canonical(value) == raw and set(value) == {'schema_version','scope','binding','passes','total_bytes'}
                and type(value['schema_version']) is int and value['schema_version'] == 1
                and value['scope'] == 'ARRAY_CONTENT_ONLY_NOT_EXECUTION_ATTESTATION'
                and value['binding'] == expected_binding and len(value['passes']) == 2, 'manifest schema differs')
        names, total, outputs, commitments, raws = [], 0, [], [], []
        ids = [t['trial_id'] for t in trials]
        for index, part in enumerate(value['passes']):
            require(set(part) == {'pass_id','batch_size','trial_ids','boundaries','official_outputs','original_pass_evidence'}
                    and (part['pass_id'],part['batch_size'],part['trial_ids'])
                    == (('pass1',16,ids),('pass2',1,ids))[index], 'pass schedule differs')
            original = part['original_pass_evidence']
            decoded = diag.decode_pass_evidence(original)
            payload = decoded['payload']
            require(all(payload[k] == part[k] for k in ('pass_id','batch_size','trial_ids')), 'committed pass identity differs')
            commitments.append(original['commitment']['binding_sha256'])
            boundaries = payload['boundaries']
            require(set(boundaries['derived']) == set(codec.DERIVED), 'derived inventory differs')
            raws.append(tuple(boundaries[n]['aggregate']['sha256'] for n in ('raw_scene','raw_cue')))
            for family, order in (('boundaries',codec.COARSE+codec.DERIVED), ('official_outputs',codec.OFFICIAL)):
                require(set(part[family]) == set(order), 'array inventory differs')
                for name in order:
                    record = part[family][name]
                    require(set(record) == {'file','dtype','shape','nbytes','sha256'}
                            and record['file'] == f'{len(names):03d}.bin', 'array order/schema differs')
                    bound = boundaries[name] if name in codec.COARSE else boundaries['derived'][name]
                    expected = descriptor(bound['aggregate'])
                    tensor = bound['tensor']
                    require(tensor['shape'] == expected['shape'] and DTYPES[tensor['dtype']] == expected['dtype']
                            and tensor['sha256'] == expected['sha256'], 'aggregate/tensor differs')
                    rows = bound['per_trial']
                    require([r['trial_id'] for r in rows] == ids
                            and all(r['boundary'] == name and r['batch_axis'] == 0 for r in rows), 'row identity differs')
                    codec.metadata(record)
                    total += record['nbytes']
                    require(total <= codec.MAX_TOTAL, 'total byte budget exceeded')
                    codec.read_array(fd,record,expected,rows=[descriptor(r,scalar=True) for r in rows])
                    if family == 'official_outputs':
                        array = decoded['outputs'][name]
                        require(array.shape == (32,) and array.dtype.str == record['dtype']
                                and array.nbytes == record['nbytes'] and sha(array.tobytes()) == record['sha256'],
                                'official lossless encoding differs')
                    names.append(record['file'])
            outputs.append(decoded['outputs'])
        require(type(value['total_bytes']) is int and total == value['total_bytes']
                and len(names) == 40 and set(os.listdir(fd)) == {'manifest.json',*names}, 'archive inventory/size differs')
        require(raws[0] == raws[1], 'raw input changed between batch sizes')
        numeric = numeric_summary(outputs)
        summary = receipt['cell_summary']
        require(summary['status'] == ('G2_CELL_CANDIDATE_COMPLETE' if expected_binding['trust_domain'] == 'production'
                                      else 'HERMETIC_G2_CELL_COMPLETE')
                and all(summary[k] is False for k in ('production_ready','production_interference_validated',
                                                       'independent_results_verified','ready_for_gpu'))
                and type(summary['jobs_submitted']) is int and summary['jobs_submitted'] == 0,
                'cell summary overstates scope')
        require(commitments == receipt['pass_commitments'] == summary['pass_commitments']
                and summary['profile'] == expected_binding['profile']
                and summary['trial_identity_sha256'] == expected_binding['trial_identity_sha256']
                and summary['trust_domain'] == expected_binding['trust_domain']
                and summary['numeric'] == numeric, 'claimed cell numeric decision/identity differs')
        codec.check_named_directory(root,fd)
        bridge._check_module(diag)
        return dict(status='G2_ARCHIVE_CONTENT_VERIFIED', arrays_rehashed=40, per_trial_hashes_checked=1280,
                    numeric=numeric, pass_commitments=commitments, archive_manifest_sha256=digest,
                    binding=expected_binding, execution_authority_verified=False,
                    production_interference_validated=False, production_ready=False,
                    independent_results_verified=False, ready_for_gpu=False, jobs_submitted=0)
    finally:
        os.close(fd)
