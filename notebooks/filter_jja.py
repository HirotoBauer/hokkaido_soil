import re
from datetime import datetime
from pathlib import Path

import numpy as np

project_root = Path().cwd()
print(project_root)

datadir = project_root / "data"

fpaths = list((datadir / "SMAP_1km_hokkaido").glob("*.tif*"))
print(f"Found {len(fpaths)} files to filter")

date_pattern1 = re.compile(r"(\d{4})(\d{2})\d{2}")
date_pattern2 = re.compile(r"(\d{4})(\d{3})")

valid_years = np.arange(2015, 2023 + 1, 1)
valid_months = ["06", "07", "08"]

for f in fpaths:
    year = None
    month = None

    match1 = date_pattern1.search(f.name)
    if match1:
        year, month = match1.group(1), match1.group(2)
    else:
        match2 = date_pattern2.search(f.name)
        if match2:
            year, doy = match2.group(1), match2.group(2)
            dt = datetime.datetime.strptime(f"{year}{doy}", "%Y%j")
            month = dt.strftime("%m")

    if year is None or month is None:
        print(f"Skipping (no date match): {f.name}")
        continue

    if month in valid_months and int(year) in valid_years:
        # keep file
        continue
    else:
        f.unlink(missing_ok=True)
        print(f"Deleting {f.name}")
