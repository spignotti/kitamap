# KitaMap Berlin

GIS pipeline for daycare (Kita) supply in Berlin (BHT Berlin, 2024): OSM extraction, capacity estimation, demographic forecasting, accessibility isochrones (OpenRouteService), CARTO dashboard exports. An academic report (PDF) exists. **The numerical results of all analyses must be preserved exactly**: the first constraint for every edit.

## Rules
- English for code, comments, docstrings and markdown. German strings that are data values (column names, category labels in the GeoJSON exports) must not change: they feed the CARTO dashboard.
- Notebooks run in order 01, 02, 04, 03 and read each other's outputs; do not reorder or combine. Edit only through the Jupytext `.py` pairs (percent format), never the `.ipynb` directly; run `jupytext --sync <notebook>.ipynb` after every edit. Do not clear notebook outputs: they are the known-good reference.
- CRS: EPSG:32633 for computation, EPSG:4326 for exports.
- OpenRouteService key only via `OPENROUTESERVICE_API_KEY`; never hardcode.
- `data/raw/` contents stay unmodified.
- No logic changes (no algorithm, control-flow or new computation), no restructuring (directory structure is final), no runtime dependency changes (`requirements.txt` is locked). Re-running a notebook must give identical outputs.
- `docs/methodology.md` is substantive; keep it.
