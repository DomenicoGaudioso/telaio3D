# app.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from src import (
    read_xlsx, write_xlsx, ensure_sheets, validate_sheets,
    solve_linear_static_opensees_3d, results_to_sheets
)

st.set_page_config(page_title="Telaio3D Web — OpenSeesPy", layout="wide")

st.title("Telaio3D Web (Streamlit) — XLSX editor + Linear Static OpenSeesPy")
st.caption("Genera parametri → modifica tabelle → Solve 3D (OpenSeesPy) → esporta XLSX con risultati")


def generate_telaio_3d(distanzeX: list, distanzeY: list, altezzeZ: list, E: float, A: float, Iy: float, Iz: float):
    """Genera nodes ed elements per un telaio 3D parametrico."""
    nodes = []
    elements = []
    
    x_cum = [0.0]
    for d in distanzeX:
        x_cum.append(x_cum[-1] + d)
    
    y_cum = [0.0]
    for d in distanzeY:
        y_cum.append(y_cum[-1] + d)
    
    z_cum = [0.0]
    for h in altezzeZ:
        z_cum.append(z_cum[-1] + h)
    
    node_id = 1
    node_map = {}
    
    for iz, z in enumerate(z_cum):
        for iy, y in enumerate(y_cum):
            for ix, x in enumerate(x_cum):
                node_map[(iz, iy, ix)] = node_id
                nodes.append({"id": node_id, "x": x, "y": y, "z": z})
                node_id += 1
    
    elem_id = 1
    travi_ids = []
    
    # Travi orizzontali X (parallelo a X)
    for iz in range(1, len(z_cum)):
        for iy in range(len(y_cum)):
            for ix in range(len(x_cum) - 1):
                n1 = node_map[(iz, iy, ix)]
                n2 = node_map[(iz, iy, ix + 1)]
                elements.append({"id": elem_id, "n1": n1, "n2": n2, "prop": 1, "type": "beam3d"})
                travi_ids.append(elem_id)
                elem_id += 1
    
    # Travi orizzontali Y (parallelo a Y)
    for iz in range(1, len(z_cum)):
        for iy in range(len(y_cum) - 1):
            for ix in range(len(x_cum)):
                n1 = node_map[(iz, iy, ix)]
                n2 = node_map[(iz, iy + 1, ix)]
                elements.append({"id": elem_id, "n1": n1, "n2": n2, "prop": 1, "type": "beam3d"})
                travi_ids.append(elem_id)
                elem_id += 1
    
    # Pilastri (verticali Z)
    for iz in range(1, len(z_cum)):
        for iy in range(len(y_cum)):
            for ix in range(len(x_cum)):
                n1 = node_map[(iz - 1, iy, ix)]
                n2 = node_map[(iz, iy, ix)]
                elements.append({"id": elem_id, "n1": n1, "n2": n2, "prop": 1, "type": "beam3d"})
                elem_id += 1
    
    # Carichi distribuiti su travi (non pilastri)
    dist_loads = []
    qz = -2.0
    for tid in travi_ids:
        dist_loads.append({"load_case_id": 1, "elem_id": tid, "qx0": 0.0, "qx1": 0.0, "qy0": 0.0, "qy1": 0.0, "qz0": qz, "qz1": qz})
    dist_loads_df = pd.DataFrame(dist_loads)
    
    nodes_df = pd.DataFrame(nodes)
    elements_df = pd.DataFrame(elements)
    properties_df = pd.DataFrame([
        {"id": 1, "name": "cls_30", "A": A, "E": E, "G": E/2.4, "J": Iy*2, "Iy": Iy, "Iz": Iz},
    ])
    
    # Vincoli alla base
    restraints = []
    for ix in range(len(x_cum)):
        for iy in range(len(y_cum)):
            n = node_map[(0, iy, ix)]
            restraints.append({"load_case_id": 1, "node_id": n, "ux": 1, "uy": 1, "uz": 1, "rx": 1, "ry": 1, "rz": 1})
    restraints_df = pd.DataFrame(restraints)
    
    return {
        "nodes": nodes_df,
        "elements": elements_df,
        "properties": properties_df,
        "restraints": restraints_df,
        "dist_loads": dist_loads_df,
    }


if "sheets" not in st.session_state:
    st.session_state.sheets = None
if "results" not in st.session_state:
    st.session_state.results = None
if "initialized" not in st.session_state:
    st.session_state.initialized = True

with st.sidebar:
    st.header("Generatore Telaio 3D")
    
    st.subheader("Geometry")
    campate_x_str = st.text_input("Lunghezze X (m)", "4.0, 4.0", help="es: 4.0, 4.0")
    campate_y_str = st.text_input("Larghezze Y (m)", "5.0", help="es: 5.0")
    piani_str = st.text_input("Altezze Z (m)", "3.5, 3.0, 3.0", help="es: 3.5, 3.0, 3.0")
    
    st.subheader("Proprietà materiale")
    col1, col2 = st.columns(2)
    with col1:
        E = st.number_input("E (MPa)", value=30000.0)
        A = st.number_input("A (m2)", value=0.3)
    with col2:
        Iy = st.number_input("Iy (m4)", value=0.0225)
        Iz = st.number_input("Iz (m4)", value=0.015)
    
    if st.button("Genera Telaio 3D"):
        try:
            dx = [float(x.strip()) for x in campate_x_str.split(",") if x.strip()]
            dy = [float(y.strip()) for y in campate_y_str.split(",") if y.strip()]
            dz = [float(z.strip()) for z in piani_str.split(",") if z.strip()]
            
            sheets = generate_telaio_3d(dx, dy, dz, E, A, Iy, Iz)
            sheets["load_cases"] = pd.DataFrame([{"id": 1, "name": "permanente"}])
            sheets["node_loads"] = pd.DataFrame()
                
            st.session_state.sheets = ensure_sheets(sheets)
            st.session_state.results = None
            st.success(f"Generato: {len(sheets['nodes'])} nodi, {len(sheets['elements'])} elementi")
        except Exception as e:
            st.error(f"Errore: {e}")

    st.divider()
    st.header("File")
    up = st.file_uploader("Carica input .xlsx", type=["xlsx"])
    if up is not None:
        st.session_state.sheets = ensure_sheets(read_xlsx(up.getvalue()))
        st.session_state.results = None
        st.success("XLSX caricato.")

    if st.button("📂 Carica esempio predefinito"):
        sheets = generate_telaio_3d([4.0, 4.0], [5.0], [3.5, 3.0, 3.0], 30000.0, 0.3, 0.0225, 0.015)
        sheets["load_cases"] = pd.DataFrame([{"id": 1, "name": "permanente"}])
        sheets["node_loads"] = pd.DataFrame()
        st.session_state.sheets = ensure_sheets(sheets)
        st.session_state.results = None
        st.success("Esempio caricato!")

    if st.session_state.sheets is not None:
        lc_df = st.session_state.sheets.get("load_cases", pd.DataFrame())
        if lc_df is not None and not lc_df.empty and "id" in lc_df.columns:
            lc_ids = [int(x) for x in lc_df["id"].dropna().tolist()] or [1]
        else:
            lc_ids = [1]
    else:
        lc_ids = [1]
    active_lc = st.selectbox("Load case attivo", lc_ids, index=0)

    st.divider()
    st.header("Solve (OpenSeesPy 3D)")

    if st.button("Valida modello"):
        if st.session_state.sheets is None:
            st.warning("Genera o carica un telaio prima.")
        else:
            errs = validate_sheets(st.session_state.sheets)
            if errs:
                st.error("Problemi trovati:\n" + "\n".join([f"• {e}" for e in errs]))
            else:
                st.success("OK: input coerente.")

    if st.button("Solve ▸ Linear Static 3D"):
        if st.session_state.sheets is None:
            st.warning("Genera o carica un telaio prima.")
        else:
            errs = validate_sheets(st.session_state.sheets)
            if errs:
                st.error("Correggi prima gli errori:\n" + "\n".join([f"• {e}" for e in errs]))
            else:
                try:
                    st.session_state.results = solve_linear_static_opensees_3d(
                        st.session_state.sheets,
                        int(active_lc),
                        trapezoid_segments=10,
                        geom_transf="Linear",
                    )
                    st.success("Analisi completata.")
                except Exception as ex:
                    st.exception(ex)

    st.divider()
    st.header("Export")
    if st.session_state.sheets is not None:
        out_sheets = st.session_state.sheets
        if st.session_state.results is not None:
            out_sheets = results_to_sheets(out_sheets, st.session_state.results)
        xbytes = write_xlsx(out_sheets)
        st.download_button("Scarica XLSX (con risultati)", data=xbytes, file_name="telaio3d_output.xlsx")
    else:
        st.warning("Genera o carica un telaio prima.")


labels = [
    "nodes", "elements", "properties", "load_cases",
    "restraints", "node_loads", "dist_loads", "masses",
    "results", "plot3d"
]

tabs = st.tabs(labels)


def edit_sheet(name: str, default_cols: list):
    if st.session_state.sheets is None:
        st.warning("Genera o carica un telaio prima.")
        return
    df = st.session_state.sheets.get(name, pd.DataFrame(columns=default_cols))
    if df is None:
        df = pd.DataFrame(columns=default_cols)
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, key=f"edit_{name}")
    st.session_state.sheets[name] = edited


with tabs[0]:
    st.subheader("nodes (id, x, y, z)")
    edit_sheet("nodes", ["id", "x", "y", "z"])

with tabs[1]:
    st.subheader("elements (id, n1, n2, prop, type)")
    st.caption("type: beam3d (MVP)")
    edit_sheet("elements", ["id", "n1", "n2", "prop", "type"])

with tabs[2]:
    st.subheader("properties (id, name, A, E, G, J, Iy, Iz)")
    edit_sheet("properties", ["id", "name", "A", "E", "G", "J", "Iy", "Iz"])

with tabs[3]:
    st.subheader("load_cases (id, name)")
    edit_sheet("load_cases", ["id", "name"])

with tabs[4]:
    st.subheader("restraints (load_case_id, node_id, ux, uy, uz, rx, ry, rz)")
    edit_sheet("restraints", ["load_case_id", "node_id", "ux", "uy", "uz", "rx", "ry", "rz"])

with tabs[5]:
    st.subheader("node_loads (load_case_id, node_id, fx, fy, fz, mx, my, mz)")
    edit_sheet("node_loads", ["load_case_id", "node_id", "fx", "fy", "fz", "mx", "my", "mz"])

with tabs[6]:
    st.subheader("dist_loads (load_case_id, elem_id, qx0,qx1,qy0,qy1,qz0,qz1)")
    st.caption("Trapezio approssimato come somma di -beamUniform segmentati")
    edit_sheet("dist_loads", ["load_case_id", "elem_id", "qx0", "qx1", "qy0", "qy1", "qz0", "qz1"])

with tabs[7]:
    st.subheader("masses (load_case_id, node_id, mx, my, mz)")
    edit_sheet("masses", ["load_case_id", "node_id", "mx", "my", "mz"])

with tabs[8]:
    st.subheader("results")
    if st.session_state.results is None:
        st.info("Esegui Solve per vedere i risultati.")
    else:
        st.markdown("### results_nodal")
        st.dataframe(st.session_state.results["results_nodal"], use_container_width=True)
        st.markdown("### results_elements (localForce 3D)")
        st.dataframe(st.session_state.results["results_elements"], use_container_width=True)

with tabs[9]:
    st.subheader("plot3d (schema + deformata)")
    if st.session_state.sheets is None:
        st.warning("Genera o carica un telaio prima.")
    else:
        nodes = st.session_state.sheets.get("nodes", pd.DataFrame())
        elems = st.session_state.sheets.get("elements", pd.DataFrame())

        if nodes is None or nodes.empty or elems is None or elems.empty:
            st.info("Inserisci nodes ed elements.")
        else:
            coords = {int(r["id"]):(float(r["x"]),float(r["y"]),float(r["z"])) for _, r in nodes.iterrows() if pd.notna(r.get("id"))}
            fig = go.Figure()

            # Vincoli (simplified - 3D)
            restraints = st.session_state.sheets.get("restraints", pd.DataFrame())
            if restraints is not None and not restraints.empty:
                for _, r in restraints.iterrows():
                    nid = int(r["node_id"])
                    if nid not in coords:
                        continue
                    x, y, z = coords[nid]
                    # Simplified: show as markers
                    fig.add_trace(go.Scatter3d(x=[x], y=[y], z=[z], mode='markers', marker=dict(size=5, color='red'), name='Vincolo'))

            # Carichi distribuiti
            dist_loads = st.session_state.sheets.get("dist_loads", pd.DataFrame())
            if dist_loads is not None and not dist_loads.empty:
                for _, dl in dist_loads.iterrows():
                    eid = int(dl["elem_id"])
                    qz = float(dl.get("qz0", 0))
                    elem_row = elems[elems["id"] == eid]
                    if elem_row.empty:
                        continue
                    n1 = int(elem_row.iloc[0]["n1"])
                    n2 = int(elem_row.iloc[0]["n2"])
                    if n1 not in coords or n2 not in coords:
                        continue
                    x1, y1, z1 = coords[n1]
                    x2, y2, z2 = coords[n2]
                    xm, ym, zm = (x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2
                    if qz < 0:
                        fig.add_trace(go.Scatter3d(x=[xm], y=[ym], z=[zm], mode='markers', marker=dict(size=6, color='orange'), name='Carico'))

            # Struttura
            for _, e in elems.iterrows():
                if str(e.get("type", "")).strip().lower() != "beam3d":
                    continue
                n1 = int(e["n1"]); n2 = int(e["n2"])
                if n1 not in coords or n2 not in coords:
                    continue
                x1,y1,z1 = coords[n1]; x2,y2,z2 = coords[n2]
                fig.add_trace(go.Scatter3d(x=[x1,x2], y=[y1,y2], z=[z1,z2], mode='lines',
                                           line=dict(color='#888', width=4), showlegend=False))

            if st.session_state.results is not None:
                scale = st.slider("Scala deformata", 0.0, 500.0, 50.0, 1.0)
                disp = st.session_state.results["results_nodal"].set_index("node_id")
                dcoords = {}
                for nid,(x,y,z) in coords.items():
                    ux = float(disp.loc[nid, "ux"]) if nid in disp.index else 0.0
                    uy = float(disp.loc[nid, "uy"]) if nid in disp.index else 0.0
                    uz = float(disp.loc[nid, "uz"]) if nid in disp.index else 0.0
                    dcoords[nid] = (x + scale*ux, y + scale*uy, z + scale*uz)

                for _, e in elems.iterrows():
                    if str(e.get("type", "")).strip().lower() != "beam3d":
                        continue
                    n1 = int(e["n1"]); n2 = int(e["n2"])
                    if n1 not in dcoords or n2 not in dcoords:
                        continue
                    x1,y1,z1 = dcoords[n1]; x2,y2,z2 = dcoords[n2]
                    fig.add_trace(go.Scatter3d(x=[x1,x2], y=[y1,y2], z=[z1,z2], mode='lines',
                                               line=dict(color='#1f77b4', width=6), showlegend=False))

            fig.update_layout(
                scene=dict(xaxis_title='X', yaxis_title='Y', zaxis_title='Z'),
                margin=dict(l=0,r=0,t=0,b=0),
                height=700
            )
            st.plotly_chart(fig, use_container_width=True)
