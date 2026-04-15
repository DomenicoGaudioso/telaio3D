# Telaio3D Web (Streamlit) — XLSX editor + Linear Static (OpenSeesPy)

Questa app replica lo stesso flusso della versione 2D, ma per telai 3D:
- `src.py`: funzioni (I/O XLSX, validazione, solver OpenSeesPy 3D, export risultati)
- `app.py`: UI Streamlit con tabelle editabili
- `tests/`: pytest
- `docs/`: guida HTML

## Installazione

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Avvio

```bash
streamlit run app.py
```

## Formato XLSX (fogli)

Richiesti:
- `nodes`: id, x, y, z
- `elements`: id, n1, n2, prop, type (beam3d)
- `properties`: id, name, A, E, G, J, Iy, Iz
- `load_cases`: id, name
- `restraints`: load_case_id, node_id, ux, uy, uz, rx, ry, rz
- `node_loads`: load_case_id, node_id, fx, fy, fz, mx, my, mz

Opzionali:
- `dist_loads`: load_case_id, elem_id, qx0,qx1,qy0,qy1,qz0,qz1 (trapezio)
- `masses`: load_case_id, node_id, mx, my, mz (solo traslazioni)

## Note

- Elementi: `elasticBeamColumn` 3D (A,E,G,J,Iy,Iz)
- Trasformazioni: `geomTransf('Linear', tag, vecxz)`; l'app seleziona automaticamente un vecxz non parallelo all'elemento.
- Carichi trapezoidali: approssimati con somma di `eleLoad -beamUniform` segmentati.

## Output

Dopo Solve vengono aggiunti:
- `results_nodal` (ux,uy,uz,rx,ry,rz e reazioni Fx,Fy,Fz,Mx,My,Mz)
- `results_elements` (localForce 3D: Fx,Fy,Fz,Mx,My,Mz agli estremi i/j)

## Test

```bash
pytest -q
```
