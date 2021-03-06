from __future__ import print_function, absolute_import

from textwrap import dedent

import netCDF4
import numpy
from osgeo import osr

from datacube.model import Variable, Coordinate
from datacube.storage.netcdf_writer import create_netcdf, create_coordinate, create_variable, netcdfy_data, \
    create_grid_mapping_variable, flag_mask_meanings, human_readable_flags_definition

GEO_PROJ = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],' \
           'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],' \
           'AUTHORITY["EPSG","4326"]]'

ALBERS_PROJ = """PROJCS["GDA94 / Australian Albers",
                        GEOGCS["GDA94",
                            DATUM["Geocentric_Datum_of_Australia_1994",
                                SPHEROID["GRS 1980",6378137,298.257222101,
                                    AUTHORITY["EPSG","7019"]],
                                TOWGS84[0,0,0,0,0,0,0],
                                AUTHORITY["EPSG","6283"]],
                            PRIMEM["Greenwich",0,
                                AUTHORITY["EPSG","8901"]],
                            UNIT["degree",0.01745329251994328,
                                AUTHORITY["EPSG","9122"]],
                            AUTHORITY["EPSG","4283"]],
                        UNIT["metre",1,
                            AUTHORITY["EPSG","9001"]],
                        PROJECTION["Albers_Conic_Equal_Area"],
                        PARAMETER["standard_parallel_1",-18],
                        PARAMETER["standard_parallel_2",-36],
                        PARAMETER["latitude_of_center",0],
                        PARAMETER["longitude_of_center",132],
                        PARAMETER["false_easting",0],
                        PARAMETER["false_northing",0],
                        AUTHORITY["EPSG","3577"],
                        AXIS["Easting",EAST],
                        AXIS["Northing",NORTH]]"""

SINIS_PROJ = """PROJCS["Sinusoidal",
                        GEOGCS["GCS_Undefined",
                                DATUM["Undefined",
                                SPHEROID["User_Defined_Spheroid",6371007.181,0.0]],
                                PRIMEM["Greenwich",0.0],
                                UNIT["Degree",0.0174532925199433]],
                        PROJECTION["Sinusoidal"],
                        PARAMETER["False_Easting",0.0],
                        PARAMETER["False_Northing",0.0],
                        PARAMETER["Central_Meridian",0.0],
                        UNIT["Meter",1.0]]"""

GLOBAL_ATTRS = {'test_attribute': 'test_value'}

DATA_VARIABLES = ('B1', 'B2')
LAT_LON_COORDINATES = ('latitude', 'longitude')
PROJECTED_COORDINATES = ('x', 'y')
COMMON_VARIABLES = ('crs', 'time')

DATA_WIDTH = 400
DATA_HEIGHT = 200


def _ensure_spheroid(var):
    assert 'semi_major_axis' in var.ncattrs()
    assert 'semi_minor_axis' in var.ncattrs()
    assert 'inverse_flattening' in var.ncattrs()


def test_create_albers_projection_netcdf(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    crs = osr.SpatialReference(ALBERS_PROJ)
    create_grid_mapping_variable(nco, crs)
    nco.close()

    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'crs' in nco.variables
        assert nco['crs'].grid_mapping_name == 'albers_conical_equal_area'
        assert 'standard_parallel' in nco['crs'].ncattrs()
        assert 'longitude_of_central_meridian' in nco['crs'].ncattrs()
        assert 'latitude_of_projection_origin' in nco['crs'].ncattrs()
        _ensure_spheroid(nco['crs'])


def test_create_epsg4326_netcdf(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    crs = osr.SpatialReference(GEO_PROJ)
    create_grid_mapping_variable(nco, crs)
    nco.close()

    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'crs' in nco.variables
        assert nco['crs'].grid_mapping_name == 'latitude_longitude'
        _ensure_spheroid(nco['crs'])


def test_create_sinus_netcdf(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    crs = osr.SpatialReference(SINIS_PROJ)
    create_grid_mapping_variable(nco, crs)
    nco.close()

    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'crs' in nco.variables
        assert nco['crs'].grid_mapping_name == 'sinusoidal'
        assert 'longitude_of_central_meridian' in nco['crs'].ncattrs()
        _ensure_spheroid(nco['crs'])


def test_create_string_variable(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    coord = create_coordinate(nco, 'greg', Coordinate(numpy.dtype('int'), begin=0, end=0,
                                                      length=3, units='cubic gregs'))
    coord[:] = [1, 3, 9]

    dtype = numpy.dtype('S100')
    data = numpy.array(["test-str1", "test-str2", "test-str3"], dtype=dtype)

    var = create_variable(nco, 'str_var', Variable(dtype, None, ('greg',), None))
    var[:] = netcdfy_data(data)
    nco.close()

    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'str_var' in nco.variables
        assert netCDF4.chartostring(nco['str_var'][0]) == data[0]


def test_chunksizes(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    coord1 = create_coordinate(nco, 'greg', Coordinate(numpy.dtype('int'), 0, 0, 3, 'cubic gregs'))
    coord2 = create_coordinate(nco, 'bleh', Coordinate(numpy.dtype('int'), 0, 0, 5, 'metric blehs'))

    no_chunks = create_variable(nco, 'no_chunks', Variable(numpy.dtype(int), None, ('greg', 'bleh'), None))
    min_max_chunks = create_variable(nco, 'min_max_chunks', Variable(numpy.dtype(int), None, ('greg', 'bleh'), None),
                                     chunksizes=[2, 50])
    nco.close()

    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert nco['no_chunks'].chunking() == 'contiguous'
        assert nco['min_max_chunks'].chunking() == [2, 5]


EXAMPLE_PQ_MEASUREMENT_DEF = {
    'attrs': {'standard_name': 'pixel_quality'},
    'dtype': 'int16',
    'units': '1',
    'nodata': -999,
    'src_varname': 'PQ',
    'flags_definition': {
        'band_1_saturated': {
            'bit_index': 0,
            'value': 0,
            'description': 'Band 1 is saturated'},
        'band_2_saturated': {
            'bit_index': 1,
            'value': 0,
            'description': 'Band 2 is saturated'},
        'band_3_saturated': {
            'bit_index': 2,
            'value': 0,
            'description': 'Band 3 is saturated'},
        'land_obs': {
            'bit_index': 9,
            'value': 1,
            'description': 'Land observation'},
        'sea_obs': {
            'bit_index': 9,
            'value': 0,
            'description': 'Sea observation'},
    }}

EXPECTED_HUMAN_READABLE_FLAGS = dedent("""\
        Bits are listed from the MSB (bit 9) to the LSB (bit 0)
        Bit    Value     Description
        9       1       Land observation
        9       0       Sea observation
        2       0       Band 3 is saturated
        1       0       Band 2 is saturated
        0       0       Band 1 is saturated""")


def test_measurements_model_netcdfflags():
    masks, vrange, meanings = flag_mask_meanings(EXAMPLE_PQ_MEASUREMENT_DEF['flags_definition'])
    assert ([1, 2, 4, 512] == masks).all()
    assert ([0, 1023] == vrange).all()
    assert 'no_band_1_saturated no_band_2_saturated no_band_3_saturated land_obs' == meanings


def test_measurements_model_human_readable_flags():
    assert EXPECTED_HUMAN_READABLE_FLAGS == human_readable_flags_definition(
        EXAMPLE_PQ_MEASUREMENT_DEF['flags_definition'])
