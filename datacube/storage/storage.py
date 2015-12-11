# coding=utf-8
"""
Create/store dataset data into storage units based on the provided storage mappings
"""
from __future__ import absolute_import, division, print_function

import logging

from contextlib import contextmanager

import dateutil.parser
import numpy
import rasterio.warp

from rasterio.warp import RESAMPLING
from rasterio.coords import BoundingBox
from affine import Affine
from datacube.storage.utils import ensure_path_exists
from .netcdf_writer import NetCDFWriter

from datacube import compat
from datacube.model import StorageUnit, TileSpec
from datacube.storage.netcdf_indexer import index_netcdfs

_LOG = logging.getLogger(__name__)


def generate_filename(filename_format, eodataset, tile_spec):
    merged = eodataset.copy()

    # Until we can use parsed dataset fields:
    if isinstance(merged['creation_dt'], compat.string_types):
        merged['creation_dt'] = dateutil.parser.parse(merged['creation_dt'])
    if isinstance(merged['extent']['center_dt'], compat.string_types):
        merged['extent']['center_dt'] = dateutil.parser.parse(merged['extent']['center_dt'])

    merged.update(tile_spec.__dict__)
    return filename_format.format(**merged)


def _dataset_bounds(dataset):
    geo_ref_points = dataset.metadata_doc['grid_spatial']['projection']['geo_ref_points']
    return BoundingBox(geo_ref_points['ll']['x'], geo_ref_points['ll']['y'],
                       geo_ref_points['ur']['x'], geo_ref_points['ur']['y'])


def _dataset_projection(dataset):
    projection = dataset.metadata_doc['grid_spatial']['projection']
    # TODO: projection stuff properly
    assert projection['datum'] == 'GDA94'
    return {'init': 'EPSG:283' + str(abs(projection['zone']))}


def _grid_datasets(datasets, grid_proj, grid_size):
    tiles = {}
    for dataset in datasets:
        bounds = BoundingBox(*rasterio.warp.transform_bounds(_dataset_projection(dataset),
                                                             grid_proj,
                                                             *_dataset_bounds(dataset)))

        for y in range(int(bounds.bottom//grid_size[0]), int(bounds.top//grid_size[0])+1):
            for x in range(int(bounds.left//grid_size[1]), int(bounds.right//grid_size[1])+1):
                tiles.setdefault((y, x), []).append(dataset)

    return tiles


def _dataset_time(dataset):
    center_dt = dataset.metadata_doc['extent']['center_dt']
    if isinstance(center_dt, compat.string_types):
        return dateutil.parser.parse(center_dt)
    return center_dt


def _get_tile_transform(tile_index, tile_size, tile_res):
    x = (tile_index[1] + (1 if tile_res[1] < 0 else 0)) * tile_size[1]
    y = (tile_index[0] + (1 if tile_res[0] < 0 else 0)) * tile_size[0]
    return Affine(tile_res[1], 0.0, x, 0.0, tile_res[0], y)


def _create_data_variable(ncfile, measurement_descriptor, chunking):
    varname = measurement_descriptor['varname']
    chunksizes = [chunking[dim] for dim in ['t', 'y', 'x']]
    dtype = measurement_descriptor['dtype']
    nodata = measurement_descriptor.get('nodata', None)
    units = measurement_descriptor.get('units', None)
    return ncfile.ensure_variable(varname, dtype, chunksizes, nodata, units)


def reproject_datasets(sources, destination, dst_transform, dst_projection, dst_nodata, resampling=RESAMPLING.nearest):
    buffer_ = numpy.empty(destination.shape[1:], dtype=destination.dtype)
    for index, source in enumerate(sources):
        with source.open() as src:
            rasterio.warp.reproject(src,
                                    buffer_,
                                    src_transform=source.transform,
                                    src_crs=source.projection,
                                    src_nodata=source.nodata,
                                    dst_transform=dst_transform,
                                    dst_crs=dst_projection,
                                    dst_nodata=dst_nodata,
                                    resampling=resampling,
                                    NUM_THREADS=4)
            destination[index] = buffer_


class DatasetSource(object):
    def __init__(self, dataset, measurement_id):
        dataset_measurements = dataset.collection.dataset_reader(dataset.metadata_doc).measurements_dict
        dataset_measurement_descriptor = dataset_measurements[measurement_id]
        self._filename = str(dataset.metadata_path.parent.joinpath(dataset_measurement_descriptor['path']))
        self.transform = None
        self.projection = None
        self.nodata = None

    @contextmanager
    def open(self):
        try:
            with rasterio.open(self._filename) as src:
                self.transform = src.affine
                self.projection = src.crs
                self.nodata = src.nodatavals[0]
                yield rasterio.band(src, 1)
        finally:
            src.close()


def _map_resampling(name):
    return {
        'nearest': RESAMPLING.nearest,
        'near': RESAMPLING.nearest,
        'cubic': RESAMPLING.cubic,
        'bilinear': RESAMPLING.bilinear,
        'cubic_spline': RESAMPLING.cubic_spline,
        'lanczos': RESAMPLING.lanczos,
        'average': RESAMPLING.average,
    }[name.lower()]


def store_datasets_with_mapping(datasets, mapping):
    storage_type = mapping.storage_type
    if storage_type.driver != 'NetCDF CF':
        raise RuntimeError('Storage driver is not supported (yet): %s' % storage_type.driver)

    if not mapping.storage_pattern.startswith('file://'):
        raise RuntimeError('URI protocol is not supported (yet): %s' % mapping.storage_pattern)

    tile_size = abs(storage_type.descriptor['tile_size']['y']), abs(storage_type.descriptor['tile_size']['x'])
    tile_res = storage_type.descriptor['resolution']['y'], storage_type.descriptor['resolution']['x']

    for tile_index, datasets in _grid_datasets(datasets, storage_type.projection, tile_size).items():
        datasets.sort(key=_dataset_time)

        tile_spec = TileSpec(storage_type.projection,
                             _get_tile_transform(tile_index, tile_size, tile_res),
                             width=int(tile_size[1] / abs(tile_res[1])),
                             height=int(tile_size[0] / abs(tile_res[0])))
        yield _create_storage_unit(tile_index, datasets, mapping, tile_spec, storage_type.chunking)


def _create_storage_unit(tile_index, datasets, mapping, tile_spec, chunking):
    # TODO: this needs to be better defined...
    output_filename = generate_filename(mapping.storage_pattern[7:], datasets[0].metadata_doc, tile_spec)
    ensure_path_exists(output_filename)
    _LOG.debug("Adding extracted slice to %s", output_filename)

    ncfile = NetCDFWriter(output_filename, tile_spec)
    ncfile.append_time_slices(_dataset_time(dataset) for dataset in datasets)
    for measurement_id, measurement_descriptor in mapping.measurements.items():
        var, src_filename_var = _create_data_variable(ncfile, measurement_descriptor, chunking)

        sources = (DatasetSource(dataset, measurement_id) for dataset in datasets)
        reproject_datasets(sources,
                           var,
                           tile_spec.affine,
                           tile_spec.projection,
                           measurement_descriptor.get('nodata', None),
                           resampling=_map_resampling(measurement_descriptor['resampling_method']))
    ncfile.close()
    return StorageUnit([dataset.id for dataset in datasets],
                       mapping,
                       index_netcdfs([output_filename])[output_filename],  # TODO: don't do this
                       mapping.local_path_to_location_offset('file://' + output_filename))