# src.py
from __future__ import annotations

from io import BytesIO
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import openseespy.opensees as ops

# -----------------------------
# I/O XLSX
# -----------------------------
REQUIRED_SHEETS = [
    "nodes", "elements", "properties", "load_cases",
    "restraints", "node_loads"
]
OPTIONAL_SHEETS = ["dist_loads", "masses"]


def read_xlsx(file_bytes: bytes) -> Dict[str, pd.DataFrame]:
    bio = BytesIO(file_bytes)
    xls = pd.ExcelFile(bio, engine="openpyxl")
    data: Dict[str, pd.DataFrame] = {}
    for sh in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sh, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        data[sh.strip().lower()] = df
    return data


def write_xlsx(sheets: Dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, index=False, sheet_name=name[:31])
    return bio.getvalue()


def ensure_sheets(sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    out = dict(sheets)
    for sh in REQUIRED_SHEETS:
        if sh not in out or out[sh] is None:
            out[sh] = pd.DataFrame()
    for sh in OPTIONAL_SHEETS:
        if sh not in out or out[sh] is None:
            out[sh] = pd.DataFrame()
    return out


# -----------------------------
# Validazione
# -----------------------------

def validate_sheets(sheets: Dict[str, pd.DataFrame]) -> List[str]:
    s = ensure_sheets(sheets)
    errs: List[str] = []

    def need_cols(df: pd.DataFrame, cols: List[str], name: str):
        if df is None or df.empty:
            return
        miss = [c for c in cols if c not in df.columns]
        if miss:
            errs.append(f"{name}: mancano colonne {miss}")

    need_cols(s["nodes"], ["id", "x", "y", "z"], "nodes")
    need_cols(s["elements"], ["id", "n1", "n2", "prop", "type"], "elements")
    need_cols(s["properties"], ["id", "name", "A", "E", "G", "J", "Iy", "Iz"], "properties")
    need_cols(s["load_cases"], ["id", "name"], "load_cases")
    need_cols(s["restraints"], ["load_case_id", "node_id", "ux", "uy", "uz", "rx", "ry", "rz"], "restraints")
    need_cols(s["node_loads"], ["load_case_id", "node_id", "fx", "fy", "fz", "mx", "my", "mz"], "node_loads")

    if s["dist_loads"] is not None and not s["dist_loads"].empty:
        need_cols(s["dist_loads"], [
            "load_case_id", "elem_id",
            "qx0", "qx1", "qy0", "qy1", "qz0", "qz1"
        ], "dist_loads")

    if s["masses"] is not None and not s["masses"].empty:
        need_cols(s["masses"], ["load_case_id", "node_id", "mx", "my", "mz"], "masses")

    return errs


# -----------------------------
# OpenSeesPy helpers
# -----------------------------

def _analysis_linear_static():
    """Setup minimo per analisi statica lineare."""
    ops.system("BandGeneral")
    ops.numberer("RCM")
    ops.constraints("Plain")
    ops.test("NormDispIncr", 1e-12, 10)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")


def _pick_vecxz_for_element(p1: Tuple[float,float,float], p2: Tuple[float,float,float]) -> List[float]:
    """Sceglie un vecxz non parallelo all'asse locale x (che è lungo l'elemento).

    In 3D, geomTransf Linear richiede vecxz per definire il piano locale x-z.
    Se l'elemento è quasi parallelo a Z globale, usiamo vecxz ~ Y globale; altrimenti Z globale.
    """
    dx = np.array([p2[0]-p1[0], p2[1]-p1[1], p2[2]-p1[2]], dtype=float)
    n = np.linalg.norm(dx)
    if n == 0:
        return [0.0, 0.0, 1.0]
    ex = dx / n
    # se parallelo a Z (|ex·Z| ~ 1) allora vecxz=Y
    if abs(ex.dot(np.array([0.0,0.0,1.0]))) > 0.9:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


def _apply_trapezoid_segmented_uniform(eleTag: int, qx0: float, qx1: float, qy0: float, qy1: float, qz0: float, qz1: float, nseg: int):
    """Approssima trapezio (lineare lungo l'asta) come somma di carichi uniformi.

    In OpenSeesPy eleLoad -beamUniform per 3D richiede Wy, Wz, e opzionale Wx.
    Qui applichiamo (Wy,Wz,Wx) mediando q* sul segmento.
    """
    nseg = max(1, int(nseg))
    for k in range(nseg):
        sm = (k + 0.5) / nseg
        qx = qx0 + (qx1 - qx0) * sm
        qy = qy0 + (qy1 - qy0) * sm
        qz = qz0 + (qz1 - qz0) * sm
        ops.eleLoad("-ele", int(eleTag), "-type", "-beamUniform", float(qy), float(qz), float(qx))


def solve_linear_static_opensees_3d(
    sheets: Dict[str, pd.DataFrame],
    load_case_id: int,
    trapezoid_segments: int = 10,
    geom_transf: str = "Linear",
) -> Dict[str, pd.DataFrame]:
    """Analisi statica lineare 3D con OpenSeesPy.

    - Model: basic, ndm=3, ndf=6
    - Elements: elasticBeamColumn 3D (A,E,G,J,Iy,Iz, transfTag)
    - Restraints: fix(node, ux,uy,uz,rx,ry,rz)
    - Loads: pattern Plain + timeSeries Linear + load(node, fx,fy,fz,mx,my,mz)
    - Dist loads: dist_loads trapezoidali (qx,qy,qz) -> somma di beamUniform segmentati
    - Output: nodeDisp (6 dof), nodeReaction (6 dof), eleResponse('localForce')
    """
    s = ensure_sheets(sheets)
    errs = validate_sheets(s)
    if errs:
        raise ValueError("Input non valido:\n- " + "\n- ".join(errs))

    nodes = s["nodes"].copy()
    elems = s["elements"].copy()
    props = s["properties"].copy()

    if nodes.empty or elems.empty or props.empty:
        raise ValueError("nodes/elements/properties non possono essere vuoti")

    # normalize IDs
    nodes["id"] = nodes["id"].astype(int)
    elems["id"] = elems["id"].astype(int)
    elems["n1"] = elems["n1"].astype(int)
    elems["n2"] = elems["n2"].astype(int)
    elems["prop"] = elems["prop"].astype(int)
    props["id"] = props["id"].astype(int)

    coords = {int(r["id"]): (float(r["x"]), float(r["y"]), float(r["z"])) for _, r in nodes.iterrows()}
    prop_map = {int(r["id"]): r for _, r in props.iterrows()}

    # reset
    ops.wipe()

    # model 3D 6 dof/node
    ops.model("basic", "-ndm", 3, "-ndf", 6)

    # nodes
    for nid, (x, y, z) in coords.items():
        ops.node(nid, x, y, z)

    # masses (optional) - node mass (mx,my,mz, rx,ry,rz) but we'll set translational and zero rotational
    ms = s.get("masses", pd.DataFrame())
    if ms is not None and not ms.empty:
        ms = ms[ms["load_case_id"].astype(int) == int(load_case_id)].copy()
        for _, r in ms.iterrows():
            nid = int(r["node_id"])
            mx = float(r.get("mx", 0.0))
            my = float(r.get("my", 0.0))
            mz = float(r.get("mz", 0.0))
            ops.mass(nid, mx, my, mz, 0.0, 0.0, 0.0)

    # restraints
    rr = s["restraints"]
    if rr is not None and not rr.empty:
        rr = rr[rr["load_case_id"].astype(int) == int(load_case_id)].copy()
        for _, r in rr.iterrows():
            nid = int(r["node_id"])
            ux = 1 if bool(r.get("ux", False)) else 0
            uy = 1 if bool(r.get("uy", False)) else 0
            uz = 1 if bool(r.get("uz", False)) else 0
            rx = 1 if bool(r.get("rx", False)) else 0
            ry = 1 if bool(r.get("ry", False)) else 0
            rz = 1 if bool(r.get("rz", False)) else 0
            ops.fix(nid, ux, uy, uz, rx, ry, rz)

    # coordinate transformations: create one per element group if necessary
    # We'll generate a transf tag per element based on orientation.
    transf_tags = {}
    next_transf = 1

    def get_transf_for_ele(n1: int, n2: int) -> int:
        nonlocal next_transf
        p1, p2 = coords[n1], coords[n2]
        vecxz = tuple(_pick_vecxz_for_element(p1, p2))
        key = (geom_transf, vecxz)
        if key in transf_tags:
            return transf_tags[key]
        t = next_transf
        next_transf += 1
        # OpenSeesPy geomTransf('Linear', tag, *vecxz)
        ops.geomTransf(str(geom_transf), t, *vecxz)
        transf_tags[key] = t
        return t

    # elements
    for _, e in elems.iterrows():
        if str(e.get("type", "")).strip().lower() != "beam3d":
            continue
        eleTag = int(e["id"])
        n1 = int(e["n1"])
        n2 = int(e["n2"])
        pid = int(e["prop"])
        if pid not in prop_map:
            raise ValueError(f"Elemento {eleTag}: proprietà {pid} non trovata")
        pr = prop_map[pid]
        A = float(pr["A"])
        E = float(pr["E"])
        G = float(pr["G"])
        J = float(pr["J"])
        Iy = float(pr["Iy"])
        Iz = float(pr["Iz"])
        transfTag = get_transf_for_ele(n1, n2)
        # elasticBeamColumn 3D signature: A E G J Iy Iz transfTag
        ops.element("elasticBeamColumn", eleTag, n1, n2, A, E, G, J, Iy, Iz, transfTag)

    # loads
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)

    # nodal loads
    nl = s["node_loads"]
    if nl is not None and not nl.empty:
        nl = nl[nl["load_case_id"].astype(int) == int(load_case_id)].copy()
        for _, r in nl.iterrows():
            nid = int(r["node_id"])
            fx = float(r.get("fx", 0.0))
            fy = float(r.get("fy", 0.0))
            fz = float(r.get("fz", 0.0))
            mx = float(r.get("mx", 0.0))
            my = float(r.get("my", 0.0))
            mz = float(r.get("mz", 0.0))
            ops.load(nid, fx, fy, fz, mx, my, mz)

    # distributed loads
    dl = s.get("dist_loads", pd.DataFrame())
    if dl is not None and not dl.empty:
        dl = dl[dl["load_case_id"].astype(int) == int(load_case_id)].copy()
        for _, r in dl.iterrows():
            eleTag = int(r["elem_id"])
            qx0 = float(r.get("qx0", 0.0)); qx1 = float(r.get("qx1", 0.0))
            qy0 = float(r.get("qy0", 0.0)); qy1 = float(r.get("qy1", 0.0))
            qz0 = float(r.get("qz0", 0.0)); qz1 = float(r.get("qz1", 0.0))
            _apply_trapezoid_segmented_uniform(eleTag, qx0,qx1,qy0,qy1,qz0,qz1, trapezoid_segments)

    # analysis
    _analysis_linear_static()
    ok = ops.analyze(1)
    if ok != 0:
        raise RuntimeError(f"OpenSees analyze failed with code={ok}")

    ops.reactions()

    # nodal results
    nodal_rows = []
    for nid in coords.keys():
        disp = [float(ops.nodeDisp(nid, i)) for i in range(1, 7)]
        reac = [float(ops.nodeReaction(nid, i)) for i in range(1, 7)]
        nodal_rows.append({
            "node_id": int(nid),
            "ux": disp[0], "uy": disp[1], "uz": disp[2],
            "rx": disp[3], "ry": disp[4], "rz": disp[5],
            "Fx": reac[0], "Fy": reac[1], "Fz": reac[2],
            "Mx": reac[3], "My": reac[4], "Mz": reac[5],
        })

    # element forces (local)
    elem_rows = []
    for _, e in elems.iterrows():
        if str(e.get("type", "")).strip().lower() != "beam3d":
            continue
        eleTag = int(e["id"])
        lf = ops.eleResponse(eleTag, "localForce")
        lf = list(lf) if lf is not None else []
        # Typical for 3D beam-column localForce is 12 values: [Fx,Fy,Fz,Mx,My,Mz]_i + same at j
        if len(lf) < 12:
            lf = (lf + [0.0]*12)[:12]
        out = {
            "id": eleTag,
            "n1": int(e["n1"]), "n2": int(e["n2"]),
            "Fx_i": float(lf[0]), "Fy_i": float(lf[1]), "Fz_i": float(lf[2]),
            "Mx_i": float(lf[3]), "My_i": float(lf[4]), "Mz_i": float(lf[5]),
            "Fx_j": float(lf[6]), "Fy_j": float(lf[7]), "Fz_j": float(lf[8]),
            "Mx_j": float(lf[9]), "My_j": float(lf[10]), "Mz_j": float(lf[11]),
        }
        elem_rows.append(out)

    return {
        "results_nodal": pd.DataFrame(nodal_rows),
        "results_elements": pd.DataFrame(elem_rows),
    }


def results_to_sheets(base_sheets: Dict[str, pd.DataFrame], results: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    out = dict(base_sheets)
    for k, df in results.items():
        out[k] = df
    return out
