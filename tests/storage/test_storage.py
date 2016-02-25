#    Copyright 2015 Geoscience Australia
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


from __future__ import absolute_import, division, print_function

from functools import reduce as reduce_

import netCDF4
import numpy
from affine import Affine
from mock import MagicMock

from datacube.model import Coordinate, GeoBox, Measurement
from datacube.storage.access.core import StorageUnitBase
from datacube.storage.storage import write_access_unit_to_netcdf

GEO_PROJ = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],' \
           'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],' \
           'AUTHORITY["EPSG","4326"]]'


class GeoBoxStorageUnit(StorageUnitBase):
    """ Fake Storage Unit for testing """

    def __init__(self, geobox, coordinates, variables, global_attrs=None):
        self.geobox = geobox
        self.coordinates = geobox.coordinates.copy()
        self.coordinates.update(coordinates)
        self.variables = variables
        self.global_attrs = global_attrs or {}

    @property
    def crs(self):
        return self.geobox.crs

    @property
    def affine(self):
        return self.geobox.affine

    @property
    def extent(self):
        return self.geobox.extent

    def _get_coord(self, name):
        if name in self.geobox.coordinate_labels:
            return self.geobox.coordinate_labels[name]
        else:
            coord = self.coordinates[name]
            data = numpy.linspace(coord.begin, coord.end, coord.length).astype(coord.dtype)
            return data

    def _fill_data(self, name, index, dest):
        var = self.variables[name]
        shape = tuple(self.coordinates[dim].length for dim in var.dimensions)
        size = reduce_(lambda x, y: x * y, shape, 1)
        numpy.copyto(dest, numpy.arange(size).reshape(shape)[index])


def test_write_access_unit_to_netcdf(tmpnetcdf_filename):
    affine = Affine.scale(0.1, 0.1) * Affine.translation(20, 30)
    geobox = GeoBox(100, 100, affine, GEO_PROJ)
    ds1 = GeoBoxStorageUnit(geobox,
                            {
                                'time': Coordinate(
                                    numpy.dtype(numpy.int), begin=100, end=400,
                                    length=4, units='seconds')},
                            {
                                'B10': Measurement.variable_args(
                                    dtype='float32',
                                    nodata=numpy.nan,
                                    dimensions=('time', 'latitude', 'longitude'),
                                    units='1')
                            })
    write_access_unit_to_netcdf(ds1,
                                tmpnetcdf_filename)

    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'B10' in nco.variables
        var = nco.variables['B10']
        assert (var[:] == ds1.get('B10').values).all()
