# Bundled geography

`world-map.json` is derived from Natural Earth's public-domain data:

- [Country outlines, 1:110m](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson)
- [Country names, codes, and label locations, 1:10m](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_10m_admin_0_countries.geojson)
- [Terms of use](https://www.naturalearthdata.com/about/terms-of-use/)

The asset contains 257 country/territory records and 176 outline paths. Small
countries retain marker locations even when their outlines are too small for the
world overview. Antarctica is omitted. Country names and label locations come
from the higher-resolution dataset; outlines come from the smaller dataset.

Coordinates use an equirectangular projection on a 1000 × 430 SVG canvas covering
180°W–180°E and 85°N–60°S. Paths are rounded to one decimal place; marker anchors
are rounded to two. Names include the source's English names, formal names, and
ISO codes. The browser also resolves English country names through Intl.DisplayNames.

The frontend loads this asset locally. There are no runtime requests to a mapping
provider and no generated geographic coordinates or country-specific answer text.
