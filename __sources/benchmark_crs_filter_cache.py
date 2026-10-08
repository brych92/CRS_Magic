"""Benchmark the All CRS structural filter in a QGIS Python environment."""

import json
import sys
import time
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsPointXY,
)


PLUGIN_DIRECTORY = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PLUGIN_DIRECTORY.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from crs_magic_finder_dev.find_crs import (
    CRS_FILTER_PERSIST_THRESHOLD_SECONDS,
    _ALL_CRS_MEMORY_CACHE,
    _ALL_CRS_MEMORY_CACHE_LOCK,
    findCrs,
)


def make_task():
    return findCrs(
        'Тест фільтра каталогу СК',
        [],
        QgsPointXY(0, 0),
        QgsCoordinateReferenceSystem('EPSG:3857'),
    )


application = QgsApplication([], False)
application.initQgis()

with _ALL_CRS_MEMORY_CACHE_LOCK:
    _ALL_CRS_MEMORY_CACHE.clear()

raw_srs_ids = list(QgsCoordinateReferenceSystem.validSrsIds())
fingerprint_task = make_task()
fingerprint, _ = fingerprint_task.crs_catalog_fingerprint(raw_srs_ids)
changed_fingerprint, _ = fingerprint_task.crs_catalog_fingerprint(
    raw_srs_ids + [-1]
)
assert fingerprint != changed_fingerprint

first_task = make_task()
started = time.monotonic()
first_candidates = first_task.prepare_all_crs_candidates(0)
first_elapsed = time.monotonic() - started
assert first_candidates is not None
assert first_task.catalog_cache_source in ('built', 'disk')

second_task = make_task()
started = time.monotonic()
second_candidates = second_task.prepare_all_crs_candidates(0)
second_elapsed = time.monotonic() - started
assert second_candidates is not None
assert second_task.catalog_cache_source == 'memory'
assert [item[0] for item in first_candidates] == [
    item[0] for item in second_candidates
]

disk_elapsed = None
disk_source = None
cache_path = first_task.crs_filter_cache_path(fingerprint)
cache_exists = bool(cache_path and Path(cache_path).is_file())
if first_task.catalog_filter_seconds > CRS_FILTER_PERSIST_THRESHOLD_SECONDS:
    assert cache_exists
    with _ALL_CRS_MEMORY_CACHE_LOCK:
        _ALL_CRS_MEMORY_CACHE.clear()
    disk_task = make_task()
    started = time.monotonic()
    disk_candidates = disk_task.prepare_all_crs_candidates(0)
    disk_elapsed = time.monotonic() - started
    disk_source = disk_task.catalog_cache_source
    assert disk_candidates is not None
    assert disk_source == 'disk'
    assert [item[0] for item in second_candidates] == [
        item[0] for item in disk_candidates
    ]

print(json.dumps({
    'qgis': Qgis.QGIS_VERSION,
    'catalog_count': len(raw_srs_ids),
    'candidate_count': len(first_candidates),
    'filter_seconds': round(first_task.catalog_filter_seconds, 3),
    'first_call_seconds': round(first_elapsed, 3),
    'first_source': first_task.catalog_cache_source,
    'memory_call_seconds': round(second_elapsed, 3),
    'cache_file_created': cache_exists,
    'disk_call_seconds': None if disk_elapsed is None else round(disk_elapsed, 3),
    'disk_source': disk_source,
}, ensure_ascii=False))

application.exitQgis()
