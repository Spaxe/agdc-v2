# coding=utf-8
"""
Common methods for index integration tests.
"""
from __future__ import absolute_import

import itertools
import os
import shutil
from pathlib import Path

import pytest
import rasterio
import yaml
try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

from datacube import ui
from datacube.api import API
from datacube.config import LocalConfig
from datacube.index._api import Index, _DEFAULT_COLLECTIONS_PATH, _DEFAULT_METADATA_TYPES_PATH
from datacube.index.postgres import PostgresDb
from datacube.index.postgres.tables._core import ensure_db, drop_db

_SINGLE_RUN_CONFIG_TEMPLATE = """
[locations]
testdata: {test_tile_folder}
"""

INTEGRATION_DEFAULT_CONFIG_PATH = Path(__file__).parent.joinpath('agdcintegration.conf')

_TELEMETRY_COLLECTION_DEF_PATH = Path(__file__).parent.joinpath('telemetry-collection.yaml')
_ANCILLARY_COLLECTION_DEF_PATH = Path(__file__).parent.joinpath('ancillary-collection.yaml')

_EXAMPLE_LS5_NBAR = Path(__file__).parent.joinpath('example-ls5-nbar.yaml')
_TELEMETRY_COLLECTION_DESCRIPTOR = Path(__file__).parent.joinpath('telemetry-collection.yaml')
_EXAMPLE_LS5_NBAR_DATASET_FILE = Path(__file__).parent.joinpath('example-ls5-nbar.yaml')

PROJECT_ROOT = Path(__file__).parents[1]
CONFIG_SAMPLES = PROJECT_ROOT / 'docs/config_samples/'
LS5_SAMPLES = CONFIG_SAMPLES / 'ga_landsat_5/'
LS5_NBAR_STORAGE_TYPE = LS5_SAMPLES / 'ls5_geographic.yaml'
LS5_NBAR_NAME = 'ls5_nbar'
LS5_NBAR_ALBERS_STORAGE_TYPE = LS5_SAMPLES / 'ls5_albers.yaml'
LS5_NBAR_ALBERS_NAME = 'ls5_nbar_albers'

TEST_STORAGE_SHRINK_FACTOR = 100
TEST_STORAGE_NUM_MEASUREMENTS = 2
GEOGRAPHIC_VARS = ('latitude', 'longitude')
PROJECTED_VARS = ('x', 'y')

EXAMPLE_LS5_DATASET_ID = 'bbf3e21c-82b0-11e5-9ba1-a0000100fe80'


@pytest.fixture
def integration_config_paths(tmpdir):
    test_tile_folder = str(tmpdir.mkdir('testdata'))
    test_tile_folder = Path(test_tile_folder).as_uri()
    run_config_file = tmpdir.mkdir('config').join('test-run.conf')
    run_config_file.write(
        _SINGLE_RUN_CONFIG_TEMPLATE.format(test_tile_folder=test_tile_folder)
    )
    return (
        str(INTEGRATION_DEFAULT_CONFIG_PATH),
        str(run_config_file),
        os.path.expanduser('~/.datacube_integration.conf')
    )


@pytest.fixture
def global_integration_cli_args(integration_config_paths):
    """
    The first arguments to pass to a cli command for integration test configuration.
    """
    # List of a config files in order.
    return list(itertools.chain(*(('--config_file', f) for f in integration_config_paths)))


@pytest.fixture
def local_config(integration_config_paths):
    return LocalConfig.find(integration_config_paths)


@pytest.fixture
def db(local_config):
    db = PostgresDb.from_config(local_config)
    # Drop and recreate tables so our tests have a clean db.
    drop_db(db._connection)
    ensure_db(db._connection, db._engine)
    return db


@pytest.fixture
def index(db, local_config):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    """
    return Index(db, local_config)


@pytest.fixture
def dict_api(index):
    """
    :type index: datacube.index._api.Index
    """
    return API(index=index)


@pytest.fixture
def example_ls5_dataset(tmpdir):
    # Based on LS5_TM_NBAR_P54_GANBAR01-002_090_084_19900302
    dataset_dir = tmpdir.mkdir('ls5_dataset')
    shutil.copy(str(_EXAMPLE_LS5_NBAR_DATASET_FILE), str(dataset_dir.join('agdc-metadata.yaml')))

    # Write geotiffs
    geotiff_name = "LS5_TM_NBAR_P54_GANBAR01-002_090_084_19900302_B{}0.tif"
    scene_dir = dataset_dir.mkdir('product').mkdir('scene01')
    scene_dir.join('report.txt').write('Example')
    for num in (1, 2, 3):
        path = scene_dir.join(geotiff_name.format(num))
        create_empty_geotiff(str(path))

    return Path(str(dataset_dir))


def create_empty_geotiff(path):
    metadata = {'count': 1,
                'crs': 'EPSG:28355',
                'driver': 'GTiff',
                'dtype': 'int16',
                'height': 8521,
                'nodata': -999.0,
                'transform': [25.0, 0.0, 638000.0, 0.0, -25.0, 6276000.0],
                'width': 9721}
    with rasterio.open(path, 'w', **metadata) as dst:
        pass


@pytest.fixture
def default_collection_doc():
    return list(ui.read_documents(_DEFAULT_COLLECTIONS_PATH))[0][1]


@pytest.fixture
def default_metadata_type_doc():
    return list(ui.read_documents(_DEFAULT_METADATA_TYPES_PATH))[0][1]


@pytest.fixture
def default_metadata_type(index, default_metadata_type_doc):
    return index.metadata_types.add(default_metadata_type_doc)


@pytest.fixture
def default_collection(index, default_collection_doc, default_metadata_type):
    """
    :type index: datacube.index._api.Index
    """
    return index.collections.add(default_collection_doc)


@pytest.fixture
def telemetry_collection_doc():
    return list(ui.read_documents(_TELEMETRY_COLLECTION_DEF_PATH))[0][1]


@pytest.fixture
def ancillary_collection_docs():
    return [doc for (path, doc) in ui.read_documents(_ANCILLARY_COLLECTION_DEF_PATH)]


@pytest.fixture
def telemetry_collection(index, default_metadata_type, telemetry_collection_doc):
    """
    :type index: datacube.index._api.Index
    :type telemetry_collection_doc: dict
    """
    return index.collections.add(telemetry_collection_doc)


@pytest.fixture
def ancillary_collection(index, ancillary_collection_docs):
    """
    :type index: datacube.index._api.Index
    :type ancillary_collection_docs: list[dict]
    """
    return index.collections.add(ancillary_collection_docs[0])


@pytest.fixture
def indexed_ls5_nbar_storage_type(db, index):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type index: datacube.index._api.Index
    :rtype: datacube.model.StorageType
    """
    storage_types = load_test_storage_config(LS5_NBAR_STORAGE_TYPE)

    for storage_type in storage_types:
        index.storage.types.add(storage_type)

    return index.storage.types.get_by_name(LS5_NBAR_NAME)


@pytest.fixture
def example_ls5_nbar_metadata_doc():
    return load_yaml_file(_EXAMPLE_LS5_NBAR_DATASET_FILE)[0]


@pytest.fixture
def indexed_ls5_nbar_albers_storage_type(db, index):
    storage_types = load_test_storage_config(LS5_NBAR_ALBERS_STORAGE_TYPE)

    for storage_type in storage_types:
        index.storage.types.add(storage_type)

    return index.storage.types.get_by_name(LS5_NBAR_ALBERS_NAME)


def load_test_storage_config(filename):
    storage_types = load_yaml_file(filename)
    return [alter_storage_type_for_testing(storage_type) for storage_type in storage_types]


def load_yaml_file(filename):
    with open(str(filename)) as f:
        return list(yaml.load_all(f, Loader=SafeLoader))


def alter_storage_type_for_testing(storage_type):
    storage_type = limit_num_measurements(storage_type)
    storage_type = use_test_storage(storage_type)
    if is_geogaphic(storage_type):
        return shrink_storage_type(storage_type, GEOGRAPHIC_VARS)
    else:
        return shrink_storage_type(storage_type, PROJECTED_VARS)


def limit_num_measurements(storage_type):
    measurements = storage_type['measurements']
    if len(measurements) <= TEST_STORAGE_NUM_MEASUREMENTS:
        return storage_type
    else:
        measurements_to_delete = sorted(measurements)[TEST_STORAGE_NUM_MEASUREMENTS:]
        for key in measurements_to_delete:
            del measurements[key]
        return storage_type


def use_test_storage(storage_type):
    storage_type['location_name'] = 'testdata'
    return storage_type


def is_geogaphic(storage_type):
    return 'latitude' in storage_type['storage']['resolution']


def shrink_storage_type(storage_type, variables):
    storage = storage_type['storage']
    for var in variables:
        storage['resolution'][var] = storage['resolution'][var] * TEST_STORAGE_SHRINK_FACTOR
        storage['chunking'][var] = storage['chunking'][var] / TEST_STORAGE_SHRINK_FACTOR
    return storage_type


OLD = {
    'description': 'Test LS5 Nbar 30m bands',
    'location_name': 'eotiles',
    'file_path_template': '/file_path_template/file.nc',
    'dataset_metadata': {},
    'measurements': {
        '1': {'dtype': 'int16',
              'nodata': -999,
              'resampling_method': 'cubic',
              'varname': 'band_1'},
        '2': {'dtype': 'int16',
              'nodata': -999,
              'resampling_method': 'cubic',
              'varname': 'band_2'},
        '3': {'dtype': 'int16',
              'nodata': -999,
              'resampling_method': 'cubic',
              'varname': 'band_3'},
    },
    'storage': {
        'driver': 'NetCDF CF',
        'chunking': {'time': 1, 'latitude': 400, 'longitude': 400},
        'dimension_order': ['time', 'latitude', 'longitude'],
        'crs': 'GEOGCS["WGS 84",\n'
               '    DATUM["WGS_1984",\n'
               '        SPHEROID["WGS 84",6378137,298.257223563,\n'
               '            AUTHORITY["EPSG","7030"]],\n'
               '        AUTHORITY["EPSG","6326"]],\n'
               '    PRIMEM["Greenwich",0,\n'
               '        AUTHORITY["EPSG","8901"]],\n'
               '    UNIT["degree",0.0174532925199433,\n'
               '        AUTHORITY["EPSG","9122"]],\n'
               '    AUTHORITY["EPSG","4326"]]\n',
        'resolution': {'longitude': 0.00025, 'latitude': -0.00025},
        'tile_size': {'longitude': 1.0, 'latitude': 1.0}
    }
}
