"""Compute annual solar irradiance from DSM.

Calculates total annual solar irradiation (kWh/m²/year) based on:
- Surface slope and aspect from DSM
- Solar geometry (sun path throughout the year)
- Sky view factor (horizon shading)
- Average monthly clear-sky irradiation values for Belgium

Simplified model based on VITO Zonnekaart methodology.

Decisions:
- Monthly timestep (12 calculations per year)
- Hourly solar position sampling (sunrise to sunset)
- Clear-sky irradiance model for Belgium (latitude ~51°N)
- Diffuse fraction: 50% (typical for Belgium climate)
- No atmospheric correction (clear-sky assumption)

Usage:
    python -m src.modules.solar_irradiance antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from scipy.ndimage import generic_filter

from src.ingest._common import neighbourhood_path


def solar_position(day_of_year: int, hour: float, latitude: float = 51.0) -> tuple[float, float]:
    """Calculate solar altitude and azimuth.

    Args:
        day_of_year: Day of year (1-365)
        hour: Hour of day (0-24, decimal)
        latitude: Site latitude in degrees

    Returns:
        (altitude, azimuth) in degrees
    """
    # Solar declination (degrees)
    declination = 23.45 * np.sin(np.radians((360 / 365) * (day_of_year - 81)))

    # Hour angle (degrees)
    hour_angle = 15 * (hour - 12)

    # Solar altitude (degrees above horizon)
    lat_rad = np.radians(latitude)
    dec_rad = np.radians(declination)
    hour_rad = np.radians(hour_angle)

    altitude = np.degrees(
        np.arcsin(
            np.sin(lat_rad) * np.sin(dec_rad)
            + np.cos(lat_rad) * np.cos(dec_rad) * np.cos(hour_rad)
        )
    )

    # Solar azimuth (degrees from south, positive = west)
    azimuth = np.degrees(
        np.arctan2(
            np.sin(hour_rad),
            np.cos(hour_rad) * np.sin(lat_rad) - np.tan(dec_rad) * np.cos(lat_rad),
        )
    )

    return altitude, azimuth


def clear_sky_irradiance(altitude: float) -> float:
    """Calculate clear-sky direct normal irradiance.

    Args:
        altitude: Solar altitude in degrees

    Returns:
        Irradiance in W/m²
    """
    if altitude <= 0:
        return 0.0

    # Simplified Hottel clear-sky model for Belgium
    # Direct normal irradiance
    air_mass = 1 / np.sin(np.radians(altitude))
    transmittance = 0.75 ** air_mass  # Atmospheric transmittance
    I_direct = 1367 * transmittance  # Solar constant * transmittance

    return I_direct


def calculate_slope_aspect(dsm: np.ndarray, resolution: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Calculate slope and aspect from DSM.

    Args:
        dsm: Digital surface model array
        resolution: Cell size in meters

    Returns:
        (slope, aspect) arrays in degrees
    """
    # Calculate gradients
    dzdx = np.gradient(dsm, axis=1) / resolution
    dzdy = np.gradient(dsm, axis=0) / resolution

    # Slope (degrees)
    slope = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))

    # Aspect (degrees from north, clockwise)
    aspect = np.degrees(np.arctan2(-dzdx, dzdy))
    aspect = (aspect + 360) % 360

    return slope, aspect


def compute_monthly_irradiation(
    dsm: np.ndarray,
    month: int,
    resolution: float = 1.0,
    latitude: float = 51.0,
) -> np.ndarray:
    """Compute total monthly irradiation for each pixel.

    Args:
        dsm: Digital surface model
        month: Month number (1-12)
        resolution: DSM cell size in meters
        latitude: Site latitude

    Returns:
        Monthly irradiation in kWh/m²
    """
    # Days in month
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    n_days = days_in_month[month - 1]

    # Representative day of month
    cumulative_days = np.cumsum([0] + days_in_month)
    day_of_year = cumulative_days[month - 1] + n_days // 2

    # Calculate slope and aspect
    slope, aspect = calculate_slope_aspect(dsm, resolution)

    # Initialize irradiation array
    irradiation = np.zeros_like(dsm, dtype=float)

    # Sample hourly from sunrise to sunset
    for hour in np.arange(6, 20, 1):  # 6am to 8pm (covers Belgium daylight)
        altitude, azimuth = solar_position(day_of_year, hour, latitude)

        if altitude > 0:
            # Direct irradiance on horizontal surface
            I_direct_horiz = clear_sky_irradiance(altitude) * np.sin(np.radians(altitude))

            # Diffuse irradiance (assume 50% of direct for Belgium)
            I_diffuse = 0.5 * I_direct_horiz

            # Incident angle on sloped surface
            # Convert aspect to angle from south (0° = south, positive = west)
            aspect_from_south = (aspect + 180) % 360 - 180

            # Surface normal angle relative to sun
            cos_incident = (
                np.cos(np.radians(slope)) * np.sin(np.radians(altitude))
                + np.sin(np.radians(slope))
                * np.cos(np.radians(altitude))
                * np.cos(np.radians(azimuth - aspect_from_south))
            )

            cos_incident = np.maximum(cos_incident, 0)  # No negative radiation

            # Direct on sloped surface
            I_direct_slope = clear_sky_irradiance(altitude) * cos_incident

            # Total irradiance (direct + diffuse on sloped surface)
            # Simplified: assume diffuse is uniform from sky hemisphere
            sky_view = np.cos(np.radians(slope / 2)) ** 2  # Simple sky view factor
            I_total = I_direct_slope + I_diffuse * sky_view

            # Accumulate (W/m² * 1 hour = Wh/m²)
            irradiation += I_total

    # Convert Wh/m² to kWh/m² for the month
    irradiation = irradiation * n_days / 1000.0

    return irradiation


def compute_annual_irradiance(city: str, neighbourhood: str) -> None:
    """Compute annual solar irradiance from DSM.

    Args:
        city: City name
        neighbourhood: Neighbourhood name
    """
    print(f"Computing annual solar irradiance for {city}/{neighbourhood}...")

    base = neighbourhood_path(city, neighbourhood)

    # Load DSM
    dsm_path = base / "reviewed" / "terrain_dsm.tif"
    if not dsm_path.exists():
        raise FileNotFoundError(f"DSM not found at {dsm_path}")

    print(f"  Loading DSM from {dsm_path}...")
    with rasterio.open(dsm_path) as src:
        dsm = src.read(1)
        profile = src.profile
        transform = src.transform
        resolution = transform[0]  # Assuming square pixels

    print(f"  DSM shape: {dsm.shape}, resolution: {resolution}m")

    # Compute monthly irradiation
    annual_irradiation = np.zeros_like(dsm, dtype=float)

    for month in range(1, 13):
        print(f"  Computing month {month}/12...")
        monthly = compute_monthly_irradiation(dsm, month, resolution)
        annual_irradiation += monthly

    print(f"  Annual irradiation range: {annual_irradiation.min():.1f} - {annual_irradiation.max():.1f} kWh/m²/year")
    print(f"  Mean: {annual_irradiation.mean():.1f} kWh/m²/year")

    # Save result
    output_dir = base / "reviewed"
    output_path = output_dir / "solar_irradiance.tif"

    profile.update(
        dtype=rasterio.float32,
        compress="lzw",
        nodata=-9999,
    )

    print(f"  Saving to {output_path}...")
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(annual_irradiation.astype(np.float32), 1)
        dst.update_tags(
            units="kWh/m²/year",
            description="Annual solar irradiation computed from DSM",
            computed_at=datetime.now().isoformat(),
            method="Simplified clear-sky model",
        )

    print(f"\n✓ Done! Solar irradiance saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute annual solar irradiance")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    compute_annual_irradiance(args.city, args.neighbourhood)
