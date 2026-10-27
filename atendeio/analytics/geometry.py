"""Geometria 2D em coordenadas normalizadas (0..1)."""


def point_in_polygon(x: float, y: float, pts) -> bool:
    """Ray casting; funciona para polígonos côncavos."""
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygon_area(pts) -> float:
    """Área absoluta (fórmula do cadarço)."""
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def iou(a, b) -> float:
    """Interseção sobre união de dois boxes (x1, y1, x2, y2)."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def box_overlap_fraction(box, polygon, n: int = 6) -> float:
    """Fração do BOX que cai dentro do polígono (grade n x n de pontos no box).
    Alta quando a pessoa está dentro da área, mesmo cortada pela borda do quadro."""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inside = 0
    for i in range(n):
        y = y1 + (y2 - y1) * (i + 0.5) / n
        for j in range(n):
            if point_in_polygon(x1 + (x2 - x1) * (j + 0.5) / n, y, polygon):
                inside += 1
    return inside / (n * n)


def zone_coverage_fraction(box, polygon, n: int = 8) -> float:
    """Fração do POLÍGONO coberta pelo box (grade n x n no retângulo do polígono, só os
    pontos dentro dele). Alta quando uma pessoa grande/próxima da câmera fica na frente de
    uma área pequena (ex.: a porta atrás dela), onde a fração do box seria minúscula."""
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    total = covered = 0
    for i in range(n):
        y = y0 + (y1 - y0) * (i + 0.5) / n
        for j in range(n):
            x = x0 + (x1 - x0) * (j + 0.5) / n
            if point_in_polygon(x, y, polygon):
                total += 1
                if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                    covered += 1
    return covered / total if total else 0.0


def membership_score(box, polygon) -> float:
    """Quanto a pessoa "está" na área: o maior entre (parte da pessoa na área) e
    (parte da área coberta pela pessoa)."""
    return max(box_overlap_fraction(box, polygon), zone_coverage_fraction(box, polygon))


def feet_in_zone(box, polygon, reach: float = 0.05, bottom_limit: float = 0.985) -> bool:
    """A pessoa está com os PÉS na área? Para áreas de chão (porta, fila): quem está perto da câmera
    cobre a porta na imagem mas pisa bem mais embaixo; só conta quem pisa na base da área.

    Testa o ponto dos pés e dois pontos logo acima (até `reach` do quadro), porque a base da porta
    raramente é desenhada com precisão de pixel. Se o box encosta na borda de baixo, os pés estão fora
    do quadro e não dá pra saber onde a pessoa pisa: não conta."""
    x1, _, x2, y2 = box
    if y2 >= bottom_limit:
        return False
    cx = (x1 + x2) / 2
    return any(point_in_polygon(cx, y2 - k * reach / 2, polygon) for k in range(3))


def point_polygon_distance(x: float, y: float, polygon) -> float:
    """Distância do ponto ao polígono: 0 se está dentro; senão, a menor distância até uma aresta."""
    if point_in_polygon(x, y, polygon):
        return 0.0
    best = float("inf")
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg2))
        best = min(best, ((x - (ax + t * dx)) ** 2 + (y - (ay + t * dy)) ** 2) ** 0.5)
    return best
