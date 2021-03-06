# coding=utf-8
"""
Reproject xarray.DatArray objects.

Makes assumptions on the data that it matches certain NetCDF-CF criteria
The CRS is stored as the 'spatial_ref' attribute of the 'crs' data variable
Spatial dimensions are either 'latitude' / 'longitude' or 'x' / 'y',
although this should probably instead check the 'standard_name' as defined by CF
"""
from __future__ import division, absolute_import, print_function

import xarray as xr

import rasterio
import rasterio.warp
from rasterio import Affine

import numpy as np


def reproject_like(src_data_array, like_data_array):
    src_crs = like_data_array['crs'].attrs['spatial_ref']
    dest_crs = like_data_array['crs'].attrs['spatial_ref']

    if 'latitude' in like_data_array.dims and 'longitude' in like_data_array.dims:
        dest_x_dim = 'longitude'
        dest_y_dim = 'latitude'
    elif 'x' in like_data_array.dims and 'y' in like_data_array.dims:
        dest_x_dim = 'x'
        dest_y_dim = 'y'
    else:
        raise ValueError

    src_width = like_data_array[dest_x_dim].size - 1
    src_height = like_data_array[dest_y_dim].size - 1

    src_left = float(like_data_array[dest_x_dim][0])
    src_right = float(like_data_array[dest_x_dim][-1])
    src_top = float(like_data_array[dest_y_dim][0])
    src_bottom = float(like_data_array[dest_y_dim][-1])

    dest_resolution_x = (src_right - src_left) / src_width
    dest_resolution_y = (src_bottom - src_top) / src_height
    dest_resolution = (dest_resolution_x + dest_resolution_y) / 2

    return reproject(src_data_array, src_crs, dest_crs, dest_resolution)


def reproject(src_data_array, src_crs, dst_crs, dst_resolution=None, set_nan=True):
    #TODO: Support lazy loading of data with dask imperative function
    src_data = np.copy(src_data_array.load().data)

    src_affine = _make_src_affine(src_data_array)
    dst_affine, dst_width, dst_height = _make_dst_affine(src_data_array, src_crs, dst_crs, dst_resolution)

    dst_data = np.zeros((dst_height, dst_width), dtype=src_data_array.dtype)
    nodata = _get_nodata_value(src_data_array) or -999
    with rasterio.drivers():
        rasterio.warp.reproject(source=src_data,
                                destination=dst_data,
                                src_transform=src_affine,
                                src_crs=src_crs,
                                src_nodata=nodata,
                                dst_transform=dst_affine,
                                dst_crs=dst_crs,
                                dst_nodata=nodata,
                                resampling=rasterio.warp.RESAMPLING.nearest)

    # Warp spatial coords
    coords = src_data_array.coords
    new_coords = _warp_spatial_coords(src_data_array, dst_affine, dst_width, dst_height)
    coords.update(new_coords)

    if set_nan:
        dst_data = dst_data.astype(np.float)
        dst_data[dst_data == nodata] = np.nan

    return xr.DataArray(data=dst_data, coords=coords, dims=src_data_array.dims)


def _make_dst_affine(src_data_array, src_crs, dst_crs, dst_resolution=None):
    src_bounds = _get_bounds(src_data_array)
    src_width, src_height = _get_shape(src_data_array)

    dst_affine, dst_width, dst_height = rasterio.warp.calculate_default_transform(src_crs, dst_crs,
                                                                                  src_width, src_height,
                                                                                  *src_bounds,
                                                                                  resolution=dst_resolution)
    return dst_affine, dst_width, dst_height


def _make_src_affine(src_data_array):
    src_bounds = _get_bounds(src_data_array)
    src_left, src_bottom, src_right, src_top = src_bounds
    src_resolution_x, src_resolution_y = _get_resolution(src_data_array, as_tuple=True)
    return Affine.translation(src_left, src_top) * Affine.scale(src_resolution_x, src_resolution_y)


def _get_spatial_dims(data_array):
    if 'latitude' in data_array.dims and 'longitude' in data_array.dims:
        x_dim = 'longitude'
        y_dim = 'latitude'
    elif 'x' in data_array.dims and 'y' in data_array.dims:
        x_dim = 'x'
        y_dim = 'y'
    else:
        raise KeyError

    return (x_dim, y_dim)


def _get_bounds(data_array):
    (x_dim, y_dim) = _get_spatial_dims(data_array)

    left = float(data_array[x_dim][0])
    right = float(data_array[x_dim][-1])
    top = float(data_array[y_dim][0])
    bottom = float(data_array[y_dim][-1])

    return left, bottom, right, top


def _get_shape(data_array):
    x_dim, y_dim = _get_spatial_dims(data_array)
    return data_array[x_dim].size, data_array[y_dim].size


def _get_resolution(data_array, get_avg_res=True, as_tuple=False):
    left, bottom, right, top = _get_bounds(data_array)
    width, height = _get_shape(data_array)

    resolution_x = (right - left) / (width - 1)
    resolution_y = (bottom - top) / (height - 1)
    if as_tuple:
        resolution = (resolution_x, resolution_y)
    elif get_avg_res:
        resolution = (resolution_x + resolution_y) / 2
    else:
        assert resolution_x == resolution_y
        resolution = resolution_x
    return resolution


def _get_nodata_value(data_array):
    nodata = (data_array.attrs.get('_FillValue') or
              data_array.attrs.get('missing_value') or
              data_array.attrs.get('fill_value'))
    return nodata


def _warp_spatial_coords(data_array, affine, width, height):
    ul = affine * (0, 0)
    lr = affine * (width, height)
    x_coords = np.linspace(ul[0], lr[0], num=width)
    y_coords = np.linspace(ul[1], lr[1], num=height)
    (x_dim, y_dim) = _get_spatial_dims(data_array)

    coords = {}
    coords[x_dim] = x_coords
    coords[y_dim] = y_coords

    return coords
