import sys
from pathlib import Path

import matplotlib
import rioxarray

project_root = Path().resolve()
print(project_root)

datadir = project_root / "data"
da = rioxarray.open_rasterio(
    datadir / "SMAP_400m_hokkaido" / "smap_sm_400m_2015091.tif"
)

print(da)

# 2. View spatial metadata (CRS, transform, resolution)
print("CRS:", da.rio.crs)
print("Bounds:", da.rio.bounds())
print("Resolution (dx, dy):", da.rio.resolution())
print("NoData Value:", da.rio.nodata)

# 3. View global and band attributes (where timestamps/units are often stored)
print("Attributes / Metadata:", da.attrs)

# If acquisition time is stored in the attributes or XML:
# (Common keys: 'TIFFTAG_DATETIME', 'acquisition_time', 'time')
acquisition_time = da.attrs.get("TIFFTAG_DATETIME") or da.attrs.get("time")
print("Timestamp:", acquisition_time)
