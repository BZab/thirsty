import argparse
import math
from io import BytesIO

import folium
import gpxpy
import requests
import rich.console
import rich.progress

OVERPASS_URL = "http://overpass-api.de/api/interpreter"


console = rich.console.Console()


def display_gpx_on_map(data, pois):
    """
    Display the GPX route and POIs on a map
    """

    # Create a base map centered around the middle of the GPX track
    track_latitudes = [
        point.latitude
        for track in data.tracks
        for segment in track.segments
        for point in segment.points
    ]

    track_longitudes = [
        point.longitude
        for track in data.tracks
        for segment in track.segments
        for point in segment.points
    ]

    center_lat = sum(track_latitudes) / len(track_latitudes)
    center_lon = sum(track_longitudes) / len(track_longitudes)

    map_center = [center_lat, center_lon]
    folium_map = folium.Map(location=map_center, zoom_start=12)

    # Plot the GPX track on the map
    for track in data.tracks:
        for segment in track.segments:
            # Create a list of coordinates from the GPX track segment
            track_coords = [
                (point.latitude, point.longitude) for point in segment.points
            ]
            folium.PolyLine(
                track_coords, color="blue", weight=2.5, opacity=1
            ).add_to(folium_map)

    # Plot POIs on the map
    for poi in pois:
        folium.Marker(
            location=[poi["lat"], poi["lon"]],
            popup=folium.Popup(f"""{poi['tags']["amenity"]}""", max_width=300),
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(folium_map)

    return folium_map


def download_gpx(url):
    """
    Download GPX from URL
    """

    console.print(f"⏳ Downloading GPX from {url}")

    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get("Content-Length", 0))

    data = BytesIO()

    with rich.progress.Progress() as progress:
        task = progress.add_task("[cyan] Downloading", total=total_size)

        for chunk in response.iter_content(chunk_size=1024):
            data.write(chunk)
            progress.update(task, advance=len(chunk))

    data.seek(0)
    return data


def get_bounds(gpx):
    """
    Return GPX trace bounding box [south, west, north, est]
    """

    min_lat = min(
        pt.latitude
        for trk in gpx.tracks
        for seg in trk.segments
        for pt in seg.points
    )
    max_lat = max(
        pt.latitude
        for trk in gpx.tracks
        for seg in trk.segments
        for pt in seg.points
    )
    min_lon = min(
        pt.longitude
        for trk in gpx.tracks
        for seg in trk.segments
        for pt in seg.points
    )
    max_lon = max(
        pt.longitude
        for trk in gpx.tracks
        for seg in trk.segments
        for pt in seg.points
    )
    return min_lat, min_lon, max_lat, max_lon


class Area:
    def __init__(self, min_lat, min_lon, max_lat, max_lon):
        self.min_lat = min_lat
        self.min_lon = min_lon
        self.max_lat = max_lat
        self.max_lon = max_lon

    def __str__(self):
        return f"{self.min_lat},{self.min_lon},{self.max_lat},{self.max_lon}"


class POI:
    # https://wiki.openstreetmap.org/wiki/Map_features
    # https://wiki.openstreetmap.org/wiki/Top-level_tag
    def __init__(self, *args, **kwargs):
        self._primary = None
        self._secondary = None

    def get_query_line(self, area):
        f"node[{str(self)}](str(area));"

    def __str__(self):
        ret = f'''"{self._primary}"'''
        if self._secondary is not None:
            ret += f'''="{self._secondary}"'''
        return ret


class Amenity(POI):
    # https://wiki.openstreetmap.org/wiki/Category:Amenities
    def __init__(self, secondary):
        super().__init__(
            primary="amenity", secondary=secondary, *args, **kwargs
        )


class Natural(POI):
    # https://wiki.openstreetmap.org/wiki/Key:natural
    def __init__(self, secondary):
        super().__init__(
            primary="natural", secondary=secondary, *args, **kwargs
        )


def query_POIs(pois, min_lat, min_lon, max_lat, max_lon):
    """
    pois - iterable of POI subclacces of interest
    """
    area = Area(
        min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon
    )
    poi_lines = ["  " + p.get_query_line(area) for p in pois]
    query_lines = (
        ["[out:json][timeout:25];", "("] + poi_lines + [");", "out body;"]
    )
    query = "\n".join(query_lines)
    response = requests.post(OVERPASS_URL, data=query)
    response.raise_for_status()
    return response.json()["elements"]


def query_snacks_and_drinks(min_lat, min_lon, max_lat, max_lon):
    amenities = {
        "drinking_water",
        "restaurant",
        "milk_dispenser",
        "pub",
        "shop",
        "kiosk",
        "juice_bar",
        "fuel",
    }
    naturals = {
        "spring",
    }
    pois += [Amenity(a) for a in amenities] + [Natural(n) for n in naturals]
    return query_POIs(POIS, min_lat, min_lon, max_lat, max_lon)


def query_drinking_water(min_lat, min_lon, max_lat, max_lon):
    """
    Query overpass API for water
    """
    WATER = [Amenity("drinking_water"), Natural("spring")]
    return query_POIs(WATER, min_lat, min_lon, max_lat, max_lon)


def add_waypoints_to_gpx(gpx, pois):
    """
    Add POI to GPX trace
    """

    for poi in pois:
        wpt = gpxpy.gpx.GPXWaypoint()
        wpt.latitude = poi["lat"]
        wpt.longitude = poi["lon"]
        wpt.name = "Water"
        wpt.description = "Water"
        wpt.symbol = "water-drop"
        gpx.waypoints.append(wpt)
    return gpx


def haversine(lat1, lon1, lat2, lon2):
    """
    Return distance in meter between two GPS points
    """

    R = 6371000  # Earth radius in meter
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def filter_pois_near_track(gpx, pois, max_distance_m=100):
    """
    Keep only POI near trace
    """

    points = [
        pt for trk in gpx.tracks for seg in trk.segments for pt in seg.points
    ]
    nearby_pois = []

    for poi in rich.progress.track(pois, description="Filtering POI"):
        lat, lon = poi["lat"], poi["lon"]
        if any(
            haversine(lat, lon, pt.latitude, pt.longitude) < max_distance_m
            for pt in points
        ):
            nearby_pois.append(poi)

    return nearby_pois


def main():
    parser = argparse.ArgumentParser(
        description="Add water POI to a GPX trace."
    )

    parser.add_argument("input", help="input GPX trace")

    parser.add_argument(
        "output", help="output GPX trace", type=argparse.FileType("w")
    )

    parser.add_argument(
        "-d",
        "--distance",
        type=float,
        default=100,
        help="search distance around trace",
    )

    parser.add_argument(
        "--html",
        action="store_true",
        help="generate HTML interactive map to <output>.html",
    )

    args = parser.parse_args()

    if args.input.startswith("http"):
        input = download_gpx(args.input)
    else:
        input = open(args.input, "rb")  # noqa: SIM115

    gpx = gpxpy.parse(input)
    bounds = get_bounds(gpx)
    pois = query_drinking_water(*bounds)
    pois = filter_pois_near_track(gpx, pois, max_distance_m=args.distance)
    gpx = add_waypoints_to_gpx(gpx, pois)

    args.output.write(gpx.to_xml())

    if args.html:
        map = display_gpx_on_map(gpx, pois)
        map.save(args.output.name + ".html")

    console.print(f"✅ Added {len(pois)} POI to {args.output.name}")
