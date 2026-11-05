'''
PhasePilot tab: what the closed loop is doing, read live from its files.

  Status     what the instrument is holding now, protein used against the budget, how many decisions
  Decisions  every decision in order: who made it (Muse, planner fallback, QC check, controller), the action,
             the setpoint it sent, and Muse's observation and rationale
  Muse       Muse's reasoning for the selected decision, its reply, and the evidence it was given
             (or why it was not used)
  SAM        the latest camera image with SAM's outline of each droplet (green accepted, red rejected, yellow =
             detector circle), droplets per frame and the share of detections SAM rejects
  Results    each setpoint's result as the loop saw it, and a map of the PS fraction across the space

Files (all written by the loop, nothing here controls the instrument):
  <log>/run.json, decisions.jsonl, results.csv    from loop/driver.py
  <queue>/state.json, events.csv                    from the GUI's setpoint queue
  <worker out>/part_*.parquet                       from the live analysis worker (SAM columns)

python -m phasecontrol.Main_UI.phasepilot_tab --log <rig>/loop_log/<run>
'''
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

WHO_COLOURS = {'muse': '#7b3fe4', 'planner fallback': '#808080', 'QC check': '#d62728',
               'controller': '#ff7f0e'}


def who_colour(who):
    for key, colour in WHO_COLOURS.items():
        if key in who and (key != 'controller' or '->' in who):
            return colour
    return '#808080'


def read_jsonl(path):
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


class PhasePilotTab(QtWidgets.QWidget):

    def __init__(self, parent=None, log_folder=None):
        super().__init__(parent)
        self.log = None
        self.run = {}
        self.parts = {}  # parquet path -> SAM/QC columns
        self.n_decisions = -1
        self.build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        if log_folder:
            self.set_log(log_folder)

    ##################################################################################
    # UI
    def build_ui(self):
        top = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton('Open loop run...')
        self.open_button.clicked.connect(self.on_open)
        self.run_label = QtWidgets.QLabel('No loop run')
        self.state_label = QtWidgets.QLabel('')
        self.state_label.setStyleSheet('font-size: 16pt; font-weight: bold')
        self.protein_bar = QtWidgets.QProgressBar()
        self.protein_bar.setFormat('protein %v / %m (x0.01 uL)')
        self.protein_bar.setMaximumWidth(320)
        self.muse_label = QtWidgets.QLabel('')
        for w in (self.open_button, self.run_label, self.state_label):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.muse_label)
        top.addWidget(self.protein_bar)

        # decisions
        self.decisions = QtWidgets.QTableWidget(0, 7)
        self.decisions.setHorizontalHeaderLabels(['#', 'time', 'decided by', 'action', 'setpoint', 'flows (uL/h)',
                                                  'observation / rationale'])
        self.decisions.horizontalHeader().setStretchLastSection(True)
        self.decisions.verticalHeader().setVisible(False)
        self.decisions.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.decisions.setWordWrap(True)
        self.decisions.itemSelectionChanged.connect(self.show_selected_decision)
        dec_box = self.boxed('Decisions (planner proposes, Muse decides, controller checks)', self.decisions)

        # Muse
        self.muse_text = QtWidgets.QPlainTextEdit()
        self.muse_text.setReadOnly(True)
        self.muse_text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        muse_box = self.boxed("Muse: reasoning, decision and the evidence it read (selected decision)", self.muse_text)

        # SAM
        self.sam_plot = pg.PlotWidget()
        self.sam_plot.setLabel('bottom', 'minutes into run')
        self.sam_plot.setLabel('left', 'SAM rejects (%) / droplets per frame')
        self.sam_plot.addLegend()
        self.sam_reject_curve = self.sam_plot.plot(pen=pg.mkPen('#d62728', width=2), name='SAM rejects %')
        self.drop_curve = self.sam_plot.plot(pen=pg.mkPen('#1f77b4', width=1), name='droplets/frame')
        self.sam_label = QtWidgets.QLabel('')
        self.sam_image = QtWidgets.QLabel('No SAM image yet')
        self.sam_image.setAlignment(QtCore.Qt.AlignCenter)
        self.sam_image.setMinimumHeight(300)
        self.sam_image.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.sam_image_caption = QtWidgets.QLabel('')
        self.sam_pixmap, self.sam_image_path = None, None
        sam_widget = QtWidgets.QWidget()
        sam_layout = QtWidgets.QVBoxLayout(sam_widget)
        sam_layout.setContentsMargins(0, 0, 0, 0)
        sam_layout.addWidget(self.sam_image_caption)
        sam_layout.addWidget(self.sam_image, 3)
        sam_layout.addWidget(self.sam_label)
        sam_layout.addWidget(self.sam_plot, 1)
        sam_box = self.boxed('SAM droplet QC (Segment Anything outlines each detected droplet)', sam_widget)

        # results + map
        self.results = QtWidgets.QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(['setpoint', 'composition', 'droplets', 'PS fraction', 'QC', 'status'])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.verticalHeader().setVisible(False)
        self.results.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.map_plot = pg.PlotWidget()
        # the planner GP's phase map (P(PS), faded where uncertain) and its predicted boundary, under the points
        self.map_image = pg.ImageItem(axisOrder='row-major')
        self.map_image.setZValue(-10)
        self.map_plot.addItem(self.map_image)
        self.map_boundary = pg.IsocurveItem(level=0.5, pen=pg.mkPen('w', width=2, style=QtCore.Qt.DashLine),
                                            axisOrder='row-major')
        self.map_boundary.setZValue(-5)
        self.map_plot.addItem(self.map_boundary)
        self.map_scatter = pg.ScatterPlotItem(size=14)
        self.map_plot.addItem(self.map_scatter)
        self.map_labels = []
        self.map_note = pg.TextItem('', anchor=(0, 0), color=(220, 220, 220))
        self.map_note.setZValue(20)
        self.map_plot.addItem(self.map_note)
        self.map_decision = None
        res_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        res_split.addWidget(self.results)
        res_split.addWidget(self.map_plot)
        res_box = self.boxed('Results and phase map (points = measured PS fraction, hollow = in flight; '
                             'background = planner GP, dashed = predicted boundary)', res_split)

        left = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        left.addWidget(dec_box)
        left.addWidget(res_box)
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right.addWidget(muse_box)
        right.addWidget(sam_box)
        main = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        main.addWidget(left)
        main.addWidget(right)
        main.setSizes([1000, 700])

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(main)

    @staticmethod
    def boxed(title, widget):
        box = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(box)
        layout.addWidget(widget)
        return box

    def on_open(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Open loop run folder (driver --log)')
        if folder:
            self.set_log(folder)

    def set_log(self, folder):
        self.log = Path(folder)
        self.map_decision = None
        self.run = read_json(self.log / 'run.json') or {}
        self.parts = {}
        self.n_decisions = -1
        self.run_label.setText(f'Loop run: {self.log.name}')
        model = self.run.get('muse_model') or 'not configured'
        self.muse_label.setText(f'Muse: {model}' + ('' if self.run.get('muse_key') else ' (no API key: planner fallback)'))
        budget = self.run.get('budget_ul') or 1
        self.protein_bar.setMaximum(int(budget * 100))
        self.refresh()

    ##################################################################################
    # refresh
    def refresh(self):
        if self.log is None:
            return
        self.update_state()
        recs = read_jsonl(self.log / 'decisions.jsonl')
        if len(recs) != self.n_decisions:
            self.n_decisions = len(recs)
            self.recs = recs
            self.update_decisions(recs)
            self.update_results()
        self.update_map()
        self.update_sam()

    def update_state(self):
        queue = Path(self.run.get('queue', ''))
        st = read_json(queue / 'state.json') if self.run.get('queue') else None
        recs = getattr(self, 'recs', [])
        paused = recs and recs[-1].get('action') == 'pause'
        if paused:
            self.state_label.setText(f'PAUSED ({recs[-1].get("decided_by")})')
            self.state_label.setStyleSheet('font-size: 16pt; font-weight: bold; color: #d62728')
        elif st is None:
            self.state_label.setText('')
        elif st.get('state') == 'holding':
            left = max(0, float(st['until']) - time.time())
            self.state_label.setText(f'Holding {st["id"]}  ({left:.0f} s left)')
            self.state_label.setStyleSheet('font-size: 16pt; font-weight: bold; color: #2ca02c')
        else:
            self.state_label.setText(st.get('state', '').capitalize())
            self.state_label.setStyleSheet('font-size: 16pt; font-weight: bold')
        if recs:
            used = recs[-1].get('protein_used_ul') or 0
            self.protein_bar.setValue(int(used * 100))
            self.protein_bar.setFormat(f'protein {used:.2f} / {self.run.get("budget_ul", 0):.1f} uL')

    def update_decisions(self, recs):
        t0 = self.run.get('started', recs[0]['time'] if recs else 0)
        self.decisions.setRowCount(len(recs))
        for row, r in enumerate(recs):
            flows = r.get('flows') or {}
            names = self.run.get('pumps', {})
            flow_txt = '  '.join(f'{names.get(str(k), k)} {v:g}' for k, v in flows.items() if str(k) in names)
            text = ' '.join(x for x in (r.get('observation', ''), r.get('rationale', '')) if x)
            if r.get('note'):
                text += f'  [{r["note"]}]'
            cells = [str(r['decision']), time.strftime('%H:%M:%S', time.localtime(r['time'])),
                     r.get('decided_by', ''), f'{r.get("action", "")} {r.get("arg", "")}'.strip(),
                     r.get('setpoint') or '', flow_txt, text]
            for col, val in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 2:
                    item.setForeground(QtGui.QColor(who_colour(val)))
                    item.setFont(QtGui.QFont('', -1, QtGui.QFont.Bold))
                self.decisions.setItem(row, col, item)
        self.decisions.resizeColumnsToContents()
        self.decisions.horizontalHeader().setStretchLastSection(True)
        self.decisions.resizeRowsToContents()
        if recs:
            self.decisions.selectRow(len(recs) - 1)
            self.decisions.scrollToBottom()

    def show_selected_decision(self):
        rows = self.decisions.selectionModel().selectedRows()
        if not rows or not getattr(self, 'recs', None):
            return
        r = self.recs[rows[0].row()]
        lines = [f'Decision {r["decision"]}: {r.get("decided_by")} -> {r.get("action")} {r.get("arg", "")}', '']
        if r.get('muse_reasoning'):
            lines += ["MUSE'S REASONING", r['muse_reasoning'], '']
        if r.get('muse_trace'):
            lines += ["MODEL'S OWN THINKING TRACE (from the provider)", r['muse_trace'], '']
        if r.get('muse_reply'):
            lines += [f'Muse reply ({r.get("muse_served_by") or r.get("muse_model")}, {r.get("muse_seconds", "?")} s):',
                      r['muse_reply'], '']
        if r.get('muse_error'):
            lines += [f'Muse not used: {r["muse_error"]}', '']
        if r.get('prompt'):
            lines += ['Evidence given to Muse:', r['prompt']]
        elif r.get('decided_by') == 'QC check':
            lines += ['The hard QC check paused the loop before the planner or Muse were asked.']
        self.muse_text.setPlainText('\n'.join(lines))

    def update_results(self):
        path = self.log / 'results.csv'
        try:
            res = pd.read_csv(path)
        except (OSError, ValueError, pd.errors.EmptyDataError):
            return
        res = res[res.decision == res.decision.max()]
        names = list(self.run.get('pumps', {}).values())
        self.results.setRowCount(len(res))
        spots, xs, ys = [], [], []
        self.map_results = []
        for row, r in enumerate(res.itertuples()):
            try:
                x = json.loads(r.x) if isinstance(r.x, str) else None
            except ValueError:
                x = None
            comp = '  '.join(f'{n} {v:.2f}' for n, v in zip(names, x)) if x else ''
            frac = '' if pd.isna(r.frac) else f'{r.frac:.2f}'
            status = 'in flight' if r.in_flight else 'back'
            for col, val in enumerate([r.id, comp, str(int(r.n)), frac, '' if pd.isna(r.qc) else r.qc, status]):
                self.results.setItem(row, col, QtWidgets.QTableWidgetItem(str(val)))
            if x and len(x) >= 3 and not pd.isna(r.frac):
                self.map_results.append(x)
            if x and len(x) >= 2:
                colour = pg.mkBrush(None) if pd.isna(r.frac) else pg.mkBrush(pg.intColor(0, hues=1, values=1))
                if not pd.isna(r.frac):
                    colour = pg.mkBrush(int(255 * r.frac), 60, int(255 * (1 - r.frac)), 230)
                spots.append(dict(pos=(x[0], x[1]), brush=colour, pen=pg.mkPen('w' if r.in_flight else 'k', width=2)))
                xs.append(x[0])
                ys.append(x[1])
        self.results.resizeColumnsToContents()
        self.map_scatter.setData(spots)
        for lbl in self.map_labels:
            self.map_plot.removeItem(lbl)
        self.map_labels = []
        for r, s in zip(res.itertuples(), spots):
            lbl = pg.TextItem(r.id, anchor=(0, 1))
            lbl.setPos(*s['pos'])
            self.map_plot.addItem(lbl)
            self.map_labels.append(lbl)
        if len(names) >= 2:
            self.map_plot.setLabel('bottom', f'{names[0]} (flow fraction)')
            self.map_plot.setLabel('left', f'{names[1]} (flow fraction)')

    def update_map(self):
        """Draw <log>/map.json: the GP's P(PS) over the first two pumps at the slice (third pump level) that the
        measured setpoints are closest to. Colour = P(PS) (blue mixed, red phase separated), faded where the GP is
        uncertain; the dashed line is where P(PS) = 0.5."""
        m = read_json(self.log / 'map.json')
        if not m or m.get('decision') == self.map_decision:
            return
        self.map_decision = m.get('decision')
        grid = np.asarray(m['grid'], float)
        mu, sd = np.asarray(m['mu'], float), np.asarray(m['sd'], float)
        if grid.ndim != 2 or grid.shape[1] < 2:
            return
        levels = [np.unique(grid[:, k]) for k in range(grid.shape[1])]
        slice_note = ''
        if grid.shape[1] >= 3:
            # slice at the third-pump level nearest the median of the measured setpoints
            res = self.map_results if hasattr(self, 'map_results') else []
            target = np.median([x[2] for x in res]) if res else np.median(levels[2])
            z = levels[2][np.argmin(np.abs(levels[2] - target))]
            keep = np.isclose(grid[:, 2], z)
            grid, mu, sd = grid[keep], mu[keep], sd[keep]
            slice_note = f'{m["names"][2]} = {z:.2f} slice'
        xs, ys = levels[0], levels[1]
        ix = np.searchsorted(xs, grid[:, 0])
        iy = np.searchsorted(ys, grid[:, 1])
        p = np.full((len(ys), len(xs)), np.nan)
        s_ = np.full((len(ys), len(xs)), np.nan)
        p[iy, ix] = mu
        s_[iy, ix] = sd
        rgba = np.zeros((len(ys), len(xs), 4), np.uint8)
        ok = ~np.isnan(p)
        rgba[..., 0] = np.where(ok, 255 * np.nan_to_num(p), 0)
        rgba[..., 1] = 60
        rgba[..., 2] = np.where(ok, 255 * (1 - np.nan_to_num(p)), 0)
        rgba[..., 3] = np.where(ok, 200 * np.clip(1 - 2 * np.nan_to_num(s_), 0.15, 1), 0)
        self.map_image.setImage(rgba, levels=None)
        dx = float(np.diff(xs).min()) if len(xs) > 1 else 0.05
        dy = float(np.diff(ys).min()) if len(ys) > 1 else 0.05
        tr = QtGui.QTransform()
        tr.translate(xs[0] - dx / 2, ys[0] - dy / 2)
        tr.scale(dx, dy)
        self.map_image.setTransform(tr)
        self.map_boundary.setTransform(tr)
        self.map_boundary.setData(np.where(ok, p, 0.0))
        names = list(self.run.get('pumps', {}).values())
        note = f'GP phase map after decision {self.map_decision} ({m.get("n_results", "?")} results)'
        self.map_note.setText(note + (f', {slice_note}' if slice_note else ''))
        okx, oky = np.where(ok.any(axis=0))[0], np.where(ok.any(axis=1))[0]
        if len(okx) and len(oky):  # frame the reachable region, not the whole unit square
            self.map_plot.setXRange(xs[okx[0]] - dx, xs[okx[-1]] + dx, padding=0)
            self.map_plot.setYRange(ys[oky[0]] - dy, ys[oky[-1]] + 1.5 * dy, padding=0)
            self.map_note.setPos(xs[okx[0]] - dx / 2, ys[oky[-1]] + 1.5 * dy)
        else:
            self.map_note.setPos(xs[0] - dx / 2, ys[-1] + dy / 2)

    def update_sam(self):
        out = Path(self.run.get('worker_out', ''))
        if not self.run.get('worker_out') or not out.exists():
            return
        self.update_sam_image(out / 'sam_frames')
        new = False
        for f in out.glob('part_*.parquet'):
            if f not in self.parts:
                try:
                    try:
                        self.parts[f] = pd.read_parquet(f, columns=['time', 'sam_ok'])
                    except (KeyError, ValueError):  # worker run without SAM
                        self.parts[f] = pd.read_parquet(f, columns=['time'])
                    new = True
                except OSError:
                    pass
        if not new or not self.parts:
            return
        d = pd.concat(self.parts.values(), ignore_index=True)
        t0 = self.run.get('started', d.time.min())
        d['minute'] = ((d.time - t0) / 60).round(1)
        per_frame = d.groupby('time').size()
        self.drop_curve.setData(((per_frame.index - t0) / 60).values, per_frame.values)
        if 'sam_ok' in d:
            chk = d.dropna(subset=['sam_ok'])
            if len(chk):
                g = chk.groupby((chk.time - t0) // 30)
                rej = g.sam_ok.apply(lambda s: 100 * (s == 0).mean())
                self.sam_reject_curve.setData((rej.index * 0.5).values, rej.values)
                last = chk[chk.time >= chk.time.max() - 60]
                self.sam_label.setText(
                    f'{self.run.get("sam", "SAM")}: {len(chk)} droplets checked, {int((chk.sam_ok == 0).sum())} rejected; '
                    f'last minute {100 * (last.sam_ok == 0).mean():.0f}% rejected')


    def update_sam_image(self, folder):
        pics = sorted(folder.glob('frame_*.png')) if folder.exists() else []
        if pics and pics[-1] != self.sam_image_path:
            self.sam_image_path = pics[-1]
            self.sam_pixmap = QtGui.QPixmap(str(pics[-1]))
            info = read_json(pics[-1].with_suffix('.json')) or {}
            when = time.strftime('%H:%M:%S', time.localtime(info['time'])) if info.get('time') else ''
            self.sam_image_caption.setText(
                f'Frame {info.get("frame", "?")} ({when}, {info.get("channel", "")} channel): SAM checked '
                f'{info.get("checked", "?")} droplets, rejected {info.get("rejected", "?")}  '
                f'[green = accepted, red = rejected, yellow = detector circle]')
        if self.sam_pixmap is not None:
            self.sam_image.setPixmap(self.sam_pixmap.scaled(self.sam_image.size(), QtCore.Qt.KeepAspectRatio,
                                                            QtCore.Qt.SmoothTransformation))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--log', help='loop run folder (driver --log)')
    parser.add_argument('--screenshot', help='render once offscreen and save a PNG here')
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv)
    tab = PhasePilotTab(log_folder=args.log)
    window = QtWidgets.QMainWindow()
    window.setWindowTitle('PhasePilot')
    window.setCentralWidget(tab)
    window.resize(1700, 950)
    if args.screenshot:
        tab.update_sam()
        window.show()
        app.processEvents()
        window.grab().save(args.screenshot)
        return
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
