"""Draw three static district supply figures from committed KitaMap results.

The script does not refit forecasts or rerun the analysis notebooks. It joins
already stored district capacity to the committed population table and applies
the supply-rate definition used by the district analysis:

    supply rate (%) = estimated current capacity / child population x 100

2024 population is the observed base year. 2034 population is the committed
ensemble forecast. Capacity is held constant, so the 2034 map is a scenario.

Run from the repository root:

    python docs/plot_supply_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import patheffects
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "data" / "external" / "daycare_coverage_base.geojson"
FORECAST_PATH = ROOT / "data" / "processed" / "population_forecast_2024_2034.csv"
OBSERVED_PATH = ROOT / "data" / "raw" / "population_development_2015_2024.csv"
OUTPUT_DIR = ROOT / "docs" / "figures"

DISTRICT_FIELD = "Bezirk"
CAPACITY_FIELD = "Gesamtkapazität"
POP_2024_FIELD = "Prognose_2024"
STORED_RATE_2024_FIELD = "Versorgungsgrad_2024"
CRS_DISPLAY = "EPSG:32633"

# Shared limits keep the 2024 and 2034 legends identical. The committed rates
# span about 62 to 150, and 100 means one estimated place per child.
RATE_VMIN = 60.0
RATE_VMAX = 150.0
RATE_VCENTER = 100.0
CHANGE_VMIN = -10.0
CHANGE_VMAX = 45.0

RATE_CMAP = LinearSegmentedColormap.from_list(
    "supply_rate",
    ["#9C4A32", "#E6C7BA", "#F7F5F2", "#B7D5D1", "#1F6B66"],
)
CHANGE_CMAP = LinearSegmentedColormap.from_list(
    "supply_change",
    ["#9C4A32", "#F7F5F2", "#1F6B66"],
)

# Offsets are in metres (EPSG:32633) from the centroid. They separate the
# adjacent Tempelhof-Schöneberg and Neukölln labels.
LABEL_OFFSETS_M: dict[str, tuple[float, float]] = {
    "Charlottenburg-Wilmersdorf": (0, -700),
    "Friedrichshain-Kreuzberg": (700, 700),
    "Lichtenberg": (-700, 1400),
    "Marzahn-Hellersdorf": (2200, -700),
    "Mitte": (-200, 500),
    "Neukölln": (1400, -3200),
    "Pankow": (200, 900),
    "Reinickendorf": (0, 700),
    "Spandau": (-900, 400),
    "Steglitz-Zehlendorf": (-1800, 200),
    "Tempelhof-Schöneberg": (-1700, -2600),
    "Treptow-Köpenick": (1200, -600),
}


def _load_districts() -> gpd.GeoDataFrame:
    """Join committed capacity, observed 2024 population, and the 2034 forecast."""
    districts = gpd.read_file(BASE_PATH)
    forecast = pd.read_csv(FORECAST_PATH)
    observed = pd.read_csv(OBSERVED_PATH)

    for frame, source in (
        (districts, BASE_PATH.name),
        (forecast, FORECAST_PATH.name),
        (observed, OBSERVED_PATH.name),
    ):
        names = frame[DISTRICT_FIELD]
        if names.duplicated().any():
            duplicates = sorted(names[names.duplicated()].unique())
            raise ValueError(f"Duplicate district identifiers in {source}: {duplicates}")

    observed_2024 = observed[[DISTRICT_FIELD, "2024"]].rename(columns={"2024": "observed_2024"})
    forecast_slim = forecast[[DISTRICT_FIELD, "2024", "2034"]].rename(
        columns={"2024": "forecast_table_2024", "2034": "population_2034"}
    )

    merged = districts.merge(observed_2024, on=DISTRICT_FIELD, how="outer", indicator="observed_join")
    merged = merged.merge(forecast_slim, on=DISTRICT_FIELD, how="outer", indicator="forecast_join")

    missing_observed = merged.loc[merged["observed_join"] != "both", DISTRICT_FIELD].tolist()
    missing_forecast = merged.loc[merged["forecast_join"] != "both", DISTRICT_FIELD].tolist()
    if missing_observed or missing_forecast:
        raise ValueError(
            "District join is not complete. "
            f"Observed mismatches: {missing_observed}. Forecast mismatches: {missing_forecast}."
        )

    required = [
        CAPACITY_FIELD,
        POP_2024_FIELD,
        STORED_RATE_2024_FIELD,
        "observed_2024",
        "forecast_table_2024",
        "population_2034",
    ]
    if merged[required].isna().any().any():
        raise ValueError("Joined district table contains missing values. Nothing was imputed.")

    population_mismatch = merged[POP_2024_FIELD] != merged["observed_2024"]
    table_mismatch = merged["forecast_table_2024"] != merged["observed_2024"]
    if population_mismatch.any() or table_mismatch.any():
        names = merged.loc[population_mismatch | table_mismatch, DISTRICT_FIELD].tolist()
        raise ValueError(f"2024 population columns disagree for: {names}")

    capacity = merged[CAPACITY_FIELD].astype(float)
    pop_2024 = merged[POP_2024_FIELD].astype(float)
    pop_2034 = merged["population_2034"].astype(float)
    merged["rate_2024"] = capacity / pop_2024 * 100.0
    merged["rate_2034"] = capacity / pop_2034 * 100.0
    merged["rate_change_pp"] = merged["rate_2034"] - merged["rate_2024"]

    stored = merged[STORED_RATE_2024_FIELD].astype(float)
    if (merged["rate_2024"].round(2) - stored.round(2)).abs().max() > 0.001:
        raise ValueError("Recomputed 2024 supply rates do not match Versorgungsgrad_2024.")

    if len(merged) != 12:
        raise ValueError(f"Expected 12 Berlin districts, found {len(merged)}.")

    return gpd.GeoDataFrame(merged, geometry="geometry", crs=districts.crs).to_crs(CRS_DISPLAY)


def _wrap_name(name: str) -> str:
    if "-" in name and len(name) > 14:
        left, right = name.split("-", 1)
        return f"{left}-\n{right}"
    return name


def _label_color(value: float, norm: TwoSlopeNorm, cmap: LinearSegmentedColormap) -> str:
    red, green, blue, _alpha = cmap(norm(value))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    if luminance < 0.55:
        return "#f7f7f5"
    return "#1c1c1c"


def _draw_labels(
    axis: plt.Axes,
    frame: gpd.GeoDataFrame,
    value_column: str,
    norm: TwoSlopeNorm,
    cmap: LinearSegmentedColormap,
    suffix: str,
    signed: bool,
) -> None:
    for _, row in frame.iterrows():
        anchor = row.geometry.centroid
        dx, dy = LABEL_OFFSETS_M.get(row[DISTRICT_FIELD], (0.0, 0.0))
        value = float(row[value_column])
        number = f"{value:+.1f}" if signed else f"{value:.1f}"
        color = _label_color(value, norm, cmap)
        stroke = "#1c1c1c" if color == "#f7f7f5" else "white"
        label_point = Point(anchor.x + dx, anchor.y + dy)
        axis.annotate(
            f"{_wrap_name(row[DISTRICT_FIELD])}\n{number}{suffix}",
            xy=(anchor.x, anchor.y),
            xytext=(label_point.x, label_point.y),
            ha="center",
            va="center",
            fontsize=8.0,
            linespacing=1.05,
            color=color,
            annotation_clip=False,
            path_effects=[patheffects.withStroke(linewidth=2.4, foreground=stroke)],
            arrowprops=(
                None
                if row.geometry.contains(label_point)
                else {
                    "arrowstyle": "-",
                    "color": "#5a5a5a",
                    "lw": 0.55,
                    "shrinkA": 0,
                    "shrinkB": 1,
                }
            ),
        )


def _new_axis(title: str, subtitle: str) -> tuple[plt.Figure, plt.Axes]:
    figure, axis = plt.subplots(figsize=(9.4, 8.6), dpi=130)
    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")
    axis.set_title(title, loc="left", fontsize=15, pad=18, color="#1c1c1c")
    axis.text(
        0.0,
        1.012,
        subtitle,
        transform=axis.transAxes,
        ha="left",
        va="bottom",
        fontsize=8.5,
        color="#4a4a4a",
    )
    axis.set_axis_off()
    return figure, axis


def _paint_districts(
    axis: plt.Axes,
    frame: gpd.GeoDataFrame,
    column: str,
    norm: TwoSlopeNorm,
    cmap: LinearSegmentedColormap,
) -> None:
    frame.plot(
        ax=axis,
        column=column,
        cmap=cmap,
        norm=norm,
        edgecolor="white",
        linewidth=0.8,
        legend=False,
    )
    minimum_x, minimum_y, maximum_x, maximum_y = frame.total_bounds
    pad_x = (maximum_x - minimum_x) * 0.04
    pad_y = (maximum_y - minimum_y) * 0.05
    axis.set_xlim(minimum_x - pad_x, maximum_x + pad_x)
    axis.set_ylim(minimum_y - pad_y, maximum_y + pad_y)
    axis.set_aspect("equal")


def _add_colorbar(
    figure: plt.Figure,
    axis: plt.Axes,
    norm: TwoSlopeNorm,
    cmap: LinearSegmentedColormap,
    label: str,
    ticks: list[float],
) -> None:
    scalar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    scalar.set_array([])
    colorbar = figure.colorbar(
        scalar,
        ax=axis,
        orientation="horizontal",
        fraction=0.046,
        pad=0.03,
        ticks=ticks,
    )
    colorbar.set_label(label, fontsize=9, color="#1c1c1c")
    colorbar.ax.tick_params(labelsize=8, colors="#1c1c1c", length=3)
    colorbar.outline.set_edgecolor("#d0d0d0")


def _footnote(figure: plt.Figure, text: str) -> None:
    figure.text(0.08, 0.02, text, ha="left", va="bottom", fontsize=7.4, color="#5c5c5c", wrap=True)


def _save(figure: plt.Figure, path: Path) -> None:
    figure.subplots_adjust(left=0.04, right=0.96, top=0.90, bottom=0.14)
    figure.savefig(path, dpi=130)
    plt.close(figure)


def plot_rate_map(
    frame: gpd.GeoDataFrame,
    column: str,
    title: str,
    subtitle: str,
    footnote: str,
    path: Path,
) -> None:
    """Save one supply-rate choropleth on the shared 60 to 150 percent scale."""
    norm = TwoSlopeNorm(vmin=RATE_VMIN, vcenter=RATE_VCENTER, vmax=RATE_VMAX)
    figure, axis = _new_axis(title, subtitle)
    _paint_districts(axis, frame, column, norm, RATE_CMAP)
    _draw_labels(axis, frame, column, norm, RATE_CMAP, suffix="%", signed=False)
    _add_colorbar(
        figure,
        axis,
        norm,
        RATE_CMAP,
        "Supply rate (%). 100 means one estimated place per child.",
        [60, 80, 100, 120, 140, 150],
    )
    _footnote(figure, footnote)
    _save(figure, path)


def plot_change_map(frame: gpd.GeoDataFrame, path: Path) -> None:
    """Save the 2034-minus-2024 change in percentage points."""
    norm = TwoSlopeNorm(vmin=CHANGE_VMIN, vcenter=0.0, vmax=CHANGE_VMAX)
    figure, axis = _new_axis(
        "Change in supply rate, 2024 to 2034 forecast",
        "Percentage points. Positive means the forecast rate is higher than the 2024 rate.",
    )
    _paint_districts(axis, frame, "rate_change_pp", norm, CHANGE_CMAP)
    _draw_labels(axis, frame, "rate_change_pp", norm, CHANGE_CMAP, suffix=" pp", signed=True)
    _add_colorbar(
        figure,
        axis,
        norm,
        CHANGE_CMAP,
        "Change in supply rate (percentage points)",
        [-10, -5, 0, 15, 30, 45],
    )
    _footnote(
        figure,
        "Delta = 2034 forecast rate minus 2024 rate, calculated before display rounding. "
        "Capacity is unchanged. A rise usually means the child-population forecast falls. "
        "Source: committed capacity and population files. No basemap.",
    )
    _save(figure, path)


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "text.color": "#1c1c1c",
            "axes.unicode_minus": False,
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    districts = _load_districts()

    plot_rate_map(
        districts,
        "rate_2024",
        "Daycare supply rate by district, 2024",
        "Estimated current places divided by the observed child population aged 0 to 6.",
        "2024 population is the observed base year, not a forecast. "
        "Capacity is the committed district estimate. "
        "Source: daycare_coverage_base.geojson and population_development_2015_2024.csv. No basemap.",
        OUTPUT_DIR / "supply_rate_2024.png",
    )
    plot_rate_map(
        districts,
        "rate_2034",
        "Forecast daycare supply rate by district, 2034",
        "Same estimated capacity divided by the committed 2034 child-population forecast. Not an observed count.",
        "2034 population is the stored ETS and Prophet ensemble forecast. "
        "Capacity is held at the 2024 estimate, so this is a scenario. "
        "Source: daycare_coverage_base.geojson and population_forecast_2024_2034.csv. No basemap.",
        OUTPUT_DIR / "supply_rate_2034.png",
    )
    plot_change_map(districts, OUTPUT_DIR / "supply_rate_change_2024_2034.png")

    summary = {
        "districts": int(len(districts)),
        "rate_2024_min": float(districts["rate_2024"].min()),
        "rate_2024_max": float(districts["rate_2024"].max()),
        "rate_2034_min": float(districts["rate_2034"].min()),
        "rate_2034_max": float(districts["rate_2034"].max()),
        "change_min_pp": float(districts["rate_change_pp"].min()),
        "change_max_pp": float(districts["rate_change_pp"].max()),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
