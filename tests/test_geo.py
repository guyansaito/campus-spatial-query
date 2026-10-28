from spatial import geo


def test_haversine_latitude():
    distance = geo.haversine(geo.CENTER_LON, geo.CENTER_LAT, geo.CENTER_LON, geo.CENTER_LAT + 0.001)
    assert 100 < distance < 120


def test_jump_threshold():
    assert geo.is_jump(200, 30)
    assert not geo.is_jump(100, 30)
    assert not geo.is_jump(500, 120)


def test_point_in_square():
    ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert geo.point_in_ring(0.5, 0.5, ring)
    assert not geo.point_in_ring(1.5, 0.5, ring)


def test_grid_origin_and_step():
    assert geo.grid_index(geo.MIN_LON + 1e-8, geo.MIN_LAT + 1e-8) == (0, 0)
    lon = geo.MIN_LON + 60 / geo.M_PER_DEG_LON
    assert geo.grid_index(lon, geo.MIN_LAT + 1e-8)[0] == 1


def test_campus_polygon_closed():
    ring = geo.campus_polygon()["coordinates"][0]
    assert ring[0] == ring[-1]
    assert len(ring) >= 4
