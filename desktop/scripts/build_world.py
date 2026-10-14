"""Build desktop/data/world_land.json, the coastlines the Explore page's map draws (offline, no tiles).

    npm pack world-atlas@2.0.2 && tar -xzf world-atlas-2.0.2.tgz
    python3 desktop/scripts/build_world.py package/land-50m.json

world-atlas (ISC, Mike Bostock) packages Natural Earth's 1:50m land (public domain) as TopoJSON. This decodes it
into plain rings of [longitude, latitude], rounded to 0.01° and thinned where points crowd, so the app needs no
TopoJSON library. The notice is in data/THIRD_PARTY.md.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data/world_land.json"


def main(src):
    topo = json.loads(Path(src).read_text())
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:  # quantized and delta-encoded
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(indices):
        out = []
        for i in indices:
            pts = arcs[i] if i >= 0 else arcs[~i][::-1]
            out.extend(pts if not out else pts[1:])
        return out

    rings = []
    for geom in topo["objects"]["land"]["geometries"]:
        polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
        for poly in polys:
            for r in poly:
                pts = ring(r)
                thin = [pts[0]]
                for p in pts[1:]:
                    if abs(p[0] - thin[-1][0]) + abs(p[1] - thin[-1][1]) >= 0.04:
                        thin.append(p)
                if len(thin) >= 4:
                    rings.append([[round(x, 2), round(y, 2)] for x, y in thin])
    OUT.write_text(json.dumps({"source": "Natural Earth 1:50m land via world-atlas 2.0.2", "rings": rings}, separators=(",", ":")))
    print(f"{len(rings)} rings, {sum(map(len, rings)):,} points -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
