"""Exact catalog bindings and the packaged secure runtime, using fictitious data."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from src.clinical_intelligence.next2u_promotion import lookup_pattern, promote_stars

pytestmark = pytest.mark.critical
ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'data/models/next2u_expanded_matrix.json'


def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


def test_all_reachable_promotions_have_an_exact_catalog_row():
    cat = catalog()
    missing = set()
    for base in range(1, 159):
        first = next(p for p in cat['patterns'] if p['base_id'] == base)
        for band in ['baixo', 'moderado', 'alto', 'critico']:
            for disease in [False, True]:
                for confirmation in [False, True]:
                    for progression in [False, True]:
                        stars = promote_stars(first['stars'], band,
                            disease_or_med=disease, confirmation=confirmation,
                            progression=progression)
                        row = lookup_pattern(base, band, stars, cat)
                        if not row or (row['base_id'], row['risk_band'], row['stars']) != (base, band, stars):
                            missing.add((base, band, stars))
    assert not missing, sorted(missing)


def test_catalog_preserves_original_971_rows_and_adds_unique_exact_bindings():
    cat = catalog()
    assert cat['n_expanded_patterns'] == len(cat['patterns']) == 1057
    assert len({p['id'] for p in cat['patterns']}) == 1057
    assert len({(p['base_id'], p['risk_band'], p['stars']) for p in cat['patterns']}) == 1057
    digest = hashlib.sha256(json.dumps(cat['patterns'][:971], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == '669935ef110cc0200dddc286a8de302a67d97db6e8030a3a6f590c1c5ecf5f4d'
    assert len([p for p in cat['patterns'][971:] if p['variant'] == 8]) == 43
    assert len([p for p in cat['patterns'][971:] if p['variant'] == 9]) == 43


def test_lookup_blocks_missing_ambiguous_and_empty_catalogs():
    cat = catalog()
    assert lookup_pattern(11, 'alto', 3, {}) is None
    cat['patterns'] = [p for p in cat['patterns'] if (p['base_id'], p['risk_band'], p['stars']) != (11, 'alto', 3)]
    assert lookup_pattern(11, 'alto', 3, cat) is None
    row = next(p for p in cat['patterns'] if p['base_id'] == 11)
    cat['patterns'].append(copy.deepcopy(row))
    assert lookup_pattern(11, row['risk_band'], row['stars'], cat) is None


def test_secure_catalog_and_docker_copy_match_the_authoritative_catalog():
    secure = ROOT / 'saude_responsiva_secure'
    assert (secure / 'data/models/next2u_expanded_matrix.json').read_bytes() == CATALOG_PATH.read_bytes()
    dockerfile = (secure / 'Dockerfile').read_text()
    assert 'COPY --chown=appuser:appuser data/models/ /app/data/models/' in dockerfile


def test_secure_image_layout_keeps_critical_hypoxemia_critical(tmp_path):
    # Exercise the filesystem layout with only the vendored src, not the monorepo.
    secure = ROOT / 'saude_responsiva_secure'
    shutil.copytree(secure / '_vendor_src', tmp_path / 'src')
    if (secure / 'data/models').exists():
        shutil.copytree(secure / 'data/models', tmp_path / 'data/models')
    script = '''
import json
from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine,VitalSnapshot
r=AlertMatrixEngine().evaluate(VitalSnapshot(hr=72,spo2=88))
print(json.dumps({'primary':r.primary_rule_id,'severity':r.max_severity,'stars':r.stars}))
'''
    env = dict(os.environ, PYTHONPATH=str(tmp_path), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, env=env, text=True, capture_output=True, check=True)
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {'primary': 'n2u_034', 'severity': 'critico', 'stars': 3}


def test_missing_packaged_catalog_never_downgrades_to_placeholder(tmp_path):
    shutil.copytree(ROOT / 'saude_responsiva_secure/_vendor_src', tmp_path / 'src')
    env = dict(os.environ, PYTHONPATH=str(tmp_path), PYTHONDONTWRITEBYTECODE='1')
    code = 'from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine'
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert 'NEXT2U_CATALOG_REQUIRED' in result.stderr
