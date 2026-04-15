import pandas as pd
from src import ensure_sheets, solve_linear_static_opensees_3d


def test_opensees_3d_cantilever_tip_load_runs():
    # cantilever along X, load Fy at tip
    sheets = ensure_sheets({
        "nodes": pd.DataFrame([
            {"id": 1, "x": 0.0, "y": 0.0, "z": 0.0},
            {"id": 2, "x": 1.0, "y": 0.0, "z": 0.0},
        ]),
        "elements": pd.DataFrame([
            {"id": 1, "n1": 1, "n2": 2, "prop": 1, "type": "beam3d"},
        ]),
        "properties": pd.DataFrame([
            {"id": 1, "name": "beam", "A": 0.01, "E": 210000.0, "G": 80000.0, "J": 1e-6, "Iy": 2e-6, "Iz": 1e-6},
        ]),
        "load_cases": pd.DataFrame([
            {"id": 1, "name": "LC1"},
        ]),
        "restraints": pd.DataFrame([
            {"load_case_id": 1, "node_id": 1, "ux": True, "uy": True, "uz": True, "rx": True, "ry": True, "rz": True},
        ]),
        "node_loads": pd.DataFrame([
            {"load_case_id": 1, "node_id": 2, "fx": 0.0, "fy": -10.0, "fz": 0.0, "mx": 0.0, "my": 0.0, "mz": 0.0},
        ]),
        "dist_loads": pd.DataFrame(),
        "masses": pd.DataFrame(),
    })

    res = solve_linear_static_opensees_3d(sheets, 1)
    nod = res["results_nodal"].set_index("node_id")
    assert abs(nod.loc[1, "ux"]) < 1e-9
    assert nod.loc[2, "uy"] < 0.0
