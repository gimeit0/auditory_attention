"""Fixed V3 native source-only check; no model, GPU, submission or retry."""
import json
from pathlib import Path

import preflight_fine_alpha as shared
from fine_alpha_entry import identity, verify_package
from publish_fine_alpha_v3 import LEGACY, PACKAGE, RELEASE_ROOT, REMOTE_ROOT, SHA, SCOPE

PUBLICATION = RELEASE_ROOT/'upload-v3-once/RESULT.json'
PUBLICATION_SHA = '72d903e5137788a6d77f1db848fb740e354ed517a524f367745ece7009a0eaa6'
EVIDENCE_NAME = 'source-check-v3-once'


def bootstrap_v3():
    old = "/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1/package"
    if shared.BOOTSTRAP.count(old) != 1: raise ValueError('BOOTSTRAP_TEMPLATE_CHANGED')
    text = shared.BOOTSTRAP.replace(old, REMOTE_ROOT+'/package')
    compile(text, '<v3-source-preflight>', 'exec')
    return text


def validate_publication(row):
    if (row.get('status') != 'FINE_ALPHA_V3_UPLOADED_AND_HASH_VERIFIED_NO_JOB' or
        row.get('release_sha256') != SHA or row.get('remote_root') != REMOTE_ROOT or
        type(row.get('jobs_submitted')) is not int or row['jobs_submitted'] != 0 or
        row.get('gpu_authorized') is not False or row.get('legacy_releases_unchanged') is not True or
        row.get('legacy_releases') != LEGACY):
        raise ValueError('V3_PUBLICATION_REQUIRED')
    publication = row.get('publication', {})
    if (publication.get('status') != 'FINE_ALPHA_FILES_PUBLISHED' or
        publication.get('root') != REMOTE_ROOT or publication.get('release_sha256') != SHA or
        publication.get('files') != 42 or publication.get('manifest_files') != 41):
        raise ValueError('V3_PUBLICATION_FILES')
    shared.validate_record(json.dumps(row.get('remote_check', {})).encode(), 'check', expected_sha=SHA)


def main():
    if identity(PUBLICATION)['sha256'] != PUBLICATION_SHA: raise ValueError('PUBLICATION_RECEIPT_SHA')
    row = json.loads(PUBLICATION.read_text()); validate_publication(row)
    manifest = verify_package(PACKAGE, SHA)
    if manifest['scope'] != SCOPE: raise ValueError('V3_SCOPE_REQUIRED')
    shared.main(package=PACKAGE, release_root=RELEASE_ROOT, remote_root=REMOTE_ROOT,
                digest=SHA, bootstrap=bootstrap_v3(), evidence_name=EVIDENCE_NAME,
                binding_path=Path(__file__),
                publication=dict(path=str(PUBLICATION), **identity(PUBLICATION)))


if __name__ == '__main__': main()
