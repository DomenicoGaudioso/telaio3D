import pandas as pd
from src import write_xlsx, read_xlsx, ensure_sheets


def test_roundtrip_xlsx_3d():
    sheets = ensure_sheets({
        "nodes": pd.DataFrame([{"id": 1, "x": 0.0, "y": 0.0, "z": 0.0}]),
        "elements": pd.DataFrame([{"id": 1, "n1": 1, "n2": 1, "prop": 1, "type": "beam3d"}]),
        "properties": pd.DataFrame([{"id": 1, "name": "p", "A": 0.01, "E": 210000.0, "G": 80000.0, "J": 1e-6, "Iy": 1e-6, "Iz": 1e-6}]),
        "load_cases": pd.DataFrame([{"id": 1, "name": "LC1"}]),
        "restraints": pd.DataFrame([{"load_case_id": 1, "node_id": 1, "ux": True, "uy": True, "uz": True, "rx": True, "ry": True, "rz": True}]),
        "node_loads": pd.DataFrame([{"load_case_id": 1, "node_id": 1, "fx": 0.0, "fy": 0.0, "fz": 0.0, "mx": 0.0, "my": 0.0, "mz": 0.0}]),
        "dist_loads": pd.DataFrame(),
        "masses": pd.DataFrame(),
    })
    b = write_xlsx(sheets)
    out = ensure_sheets(read_xlsx(b))
    assert "nodes" in out and not out["nodes"].empty
