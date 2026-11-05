"""PhasePilot demo window: the scientist sets the question, then watches the loop on two tabs.

  banner          optional (--banner "text"): a line above the tabs; none by default
  --record <mp4>  the window records itself (its own grab, 2 fps, wall-clock timed) - works offscreen with
                  QT_QPA_PLATFORM=offscreen, so the desktop is not needed; writes <mp4>.start (epoch of frame 0)
  Set question    beat 04 of the storyboard: question, protein budget, reserve, hold time -> log/question.json,
                  which the orchestrator waits for before it starts the loop
  PhasePilot tab  decisions (planner / Muse / QC check / controller / operator), Muse's reasoning, SAM image, map
  Live analysis   the rig GUI's live analysis tab on the worker output (traces, phase diagrams, QC)

    python demo_window.py --run-dir <run> [--cycle 50:25] [--auto 4] [--record out.mp4]
    (cycle = seconds on PhasePilot : on Live analysis)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path.home() / 'PhaseScan-Beta-control'))
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402
from phasecontrol.Main_UI.live_analysis_tab import LiveAnalysisTab, LiveFolderSource  # noqa: E402
from phasecontrol.Main_UI.phasepilot_tab import PhasePilotTab  # noqa: E402

REPLAY_BANNER = ('REPLAY  ·  recorded PhaseScan Beta3 run, 28 Oct 2026 (G3BP1 / PolyA RNA / PEG)  ·  '
                 'instrument and camera simulated from recorded frames  ·  SAM, Bayesian planner and Muse run live')
FPS = 2
DEFAULT_QUESTION = ('Where do G3BP1 / PolyA RNA / PEG droplets phase separate? Locate the phase boundary using as '
                    'little G3BP1 as possible, and stop when the map stops changing.')


class QuestionDialog(QtWidgets.QDialog):

    def __init__(self, parent=None, auto=0.0):
        super().__init__(parent)
        self.auto = auto
        self.setWindowTitle('PhasePilot: set the question')
        self.setMinimumWidth(820)
        form = QtWidgets.QFormLayout(self)
        form.setVerticalSpacing(14)
        title = QtWidgets.QLabel('What should PhasePilot find out, and what may it spend?')
        title.setStyleSheet('font-size: 18pt; font-weight: bold')
        form.addRow(title)
        self.question = QtWidgets.QPlainTextEdit(DEFAULT_QUESTION)
        self.question.setFixedHeight(90)
        self.question.setStyleSheet('font-size: 13pt')
        form.addRow('Question', self.question)
        self.budget = QtWidgets.QDoubleSpinBox()
        self.budget.setRange(0.1, 100)
        self.budget.setValue(3.0)
        self.budget.setSuffix(' uL of G3BP1 stock')
        self.reserve = QtWidgets.QDoubleSpinBox()
        self.reserve.setRange(0, 50)
        self.reserve.setValue(0.5)
        self.reserve.setSuffix(' uL must stay in the syringe')
        self.hold = QtWidgets.QSpinBox()
        self.hold.setRange(5, 600)
        self.hold.setValue(25)
        self.hold.setSuffix(' s per setpoint')
        for w in (self.budget, self.reserve, self.hold):
            w.setStyleSheet('font-size: 13pt')
        form.addRow('Protein budget', self.budget)
        form.addRow('Reserve', self.reserve)
        form.addRow('Hold time', self.hold)
        limits = QtWidgets.QLabel('Allowed conditions: aqueous total 120 uL/h, at least 2.5 uL/h per pump, compositions '
                                  'covered by the recorded run. Every setpoint is checked by the instrument controller '
                                  'before the pumps move.')
        limits.setWordWrap(True)
        form.addRow('Limits', limits)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Start PhasePilot')
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setStyleSheet('font-size: 14pt; padding: 8px 24px')
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)
        if auto:  # unattended recording: the question is typed in on screen, then Start is pressed
            self.question.setPlainText('')
            self.typed = 0
            self.typer = QtCore.QTimer(self)
            self.typer.timeout.connect(self.type_next)
            QtCore.QTimer.singleShot(int(auto * 1000), self.typer.start)
            self.typer.setInterval(35)

    def type_next(self):
        self.typed += 1
        self.question.setPlainText(DEFAULT_QUESTION[:self.typed])
        if self.typed >= len(DEFAULT_QUESTION):
            self.typer.stop()
            QtCore.QTimer.singleShot(2500, self.accept)

    def values(self):
        return dict(question=self.question.toPlainText().strip(), budget_ul=self.budget.value(),
                    reserve_ul=self.reserve.value(), hold_s=self.hold.value(), set_at=time.time())


class DemoWindow(QtWidgets.QMainWindow):

    def __init__(self, run_dir, cycle, auto=0.0, banner='', record=None):
        super().__init__()
        self.auto = auto
        self.run_dir = Path(run_dir)
        self.log_dir = self.run_dir / 'log'
        self.setWindowTitle('PhasePilot')
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if banner:
            label = QtWidgets.QLabel(banner)
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setStyleSheet('background: #7a1f1f; color: white; font-size: 12pt; font-weight: bold; padding: 6px')
            layout.addWidget(label)
        self.tabs = QtWidgets.QTabWidget()
        tab_font = self.tabs.tabBar().font()
        tab_font.setPointSize(13)
        self.tabs.tabBar().setFont(tab_font)
        self.pilot = PhasePilotTab()
        self.live = LiveAnalysisTab()
        self.tabs.addTab(self.pilot, 'PhasePilot')
        self.tabs.addTab(self.live, 'Live analysis')
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.status = QtWidgets.QLabel('')
        self.statusBar().addPermanentWidget(self.status)
        self.started = None
        self.done_at, self.after_done = None, 20
        self.cycle = cycle
        self.poll = QtCore.QTimer(self)
        self.poll.timeout.connect(self.tick)
        self.poll.start(1000)
        self.writer, self.rec_t0, self.rec_n, self.rec_last = None, None, 0, None
        if record:
            self.record_path = Path(record)
            QtCore.QTimer.singleShot(800, self.start_recording)
        QtCore.QTimer.singleShot(1500, self.ask_question)

    # ------------------------------------------------------------------ self-recording
    def start_recording(self):
        import imageio_ffmpeg
        w, h = self.width() - self.width() % 2, self.height() - self.height() % 2
        self.writer = imageio_ffmpeg.write_frames(str(self.record_path), (w, h), fps=FPS, codec='libx264',
                                                  quality=None, output_params=['-crf', '24', '-preset', 'fast'],
                                                  macro_block_size=8)
        self.writer.send(None)
        self.rec_t0 = time.time()
        Path(str(self.record_path) + '.start').write_text(f'{self.rec_t0:.3f}\n')
        self.rec_timer = QtCore.QTimer(self)
        self.rec_timer.timeout.connect(self.record_frame)
        self.rec_timer.start(int(1000 / FPS / 2))
        self.record_frame()

    def record_frame(self):
        """Keep video time = wall time: write as many copies of the current grab as the clock says are due."""
        if self.writer is None:
            return
        due = int((time.time() - self.rec_t0) * FPS) + 1
        if due <= self.rec_n:
            return
        image = self.grab().toImage().convertToFormat(QtGui.QImage.Format_RGB888)
        w, h = image.width() - image.width() % 2, image.height() - image.height() % 2
        ptr = image.constBits()
        ptr.setsize(image.byteCount())
        frame = np.frombuffer(ptr, np.uint8).reshape(image.height(), image.bytesPerLine())[:h, :w * 3].copy()
        while self.rec_n < due:
            self.writer.send(frame)
            self.rec_n += 1

    def closeEvent(self, event):
        if self.writer is not None:
            self.rec_timer.stop()
            self.record_frame()
            self.writer.close()
            self.writer = None
        super().closeEvent(event)

    def ask_question(self):
        dialog = QuestionDialog(self, auto=self.auto)
        dialog.exec_()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / 'question.json').write_text(json.dumps(dialog.values(), indent=1))
        self.started = time.time()
        self.statusBar().showMessage('Question set. PhasePilot is starting the loop...')

    def tick(self):
        if self.started is None:
            return
        if self.pilot.log is None and (self.log_dir / 'run.json').exists():
            self.pilot.set_log(self.log_dir)
            self.live.set_source(LiveFolderSource(str(self.run_dir / 'worker_out')))
            self.live.play_button.setChecked(True)
            self.statusBar().showMessage('')
        elapsed = time.time() - self.started
        self.status.setText(f'running {int(elapsed // 60):02d}:{int(elapsed % 60):02d}   ')
        if self.cycle and self.pilot.log is not None:
            on_pilot, on_live = self.cycle
            self.tabs.setCurrentIndex(0 if elapsed % (on_pilot + on_live) < on_pilot else 1)
        if (self.run_dir / 'DONE').exists():
            self.tabs.setCurrentIndex(0)
            self.cycle = None
            if self.writer is not None and self.done_at is None:
                self.done_at = time.time()
            if self.done_at is not None and time.time() - self.done_at > self.after_done:
                self.close()
                QtWidgets.QApplication.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--cycle', help='seconds on PhasePilot:on Live analysis, e.g. 50:25; omit for no cycling')
    parser.add_argument('--windowed', action='store_true')
    parser.add_argument('--auto', type=float, default=0, help='unattended: start typing the question after '
                        'this many seconds and press Start when done (0 = wait for the scientist)')
    parser.add_argument('--banner', default='', help='text for a red line above the tabs ("replay" = the stock replay note)')
    parser.add_argument('--record', help='MP4 to record the window to (2 fps); the window closes 20 s after DONE')
    parser.add_argument('--size', default='1920x1080', help='window size when not full screen')
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    cycle = tuple(int(v) for v in args.cycle.split(':')) if args.cycle else None
    banner = REPLAY_BANNER if args.banner == 'replay' else args.banner
    window = DemoWindow(args.run_dir, cycle, auto=args.auto, banner=banner, record=args.record)
    w, h = (int(v) for v in args.size.split('x'))
    if args.windowed or args.record:
        if args.record:
            window.setFixedSize(w, h)  # the recording must be exactly this size whatever the layout asks for
        else:
            window.resize(w, h)
        window.show()
    else:
        window.showFullScreen()
    window.raise_()
    window.activateWindow()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: app.quit())  # close the recording cleanly on kill
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QtCore.QTimer()  # let Python see signals while Qt's loop runs
    keepalive.timeout.connect(lambda: None)
    keepalive.start(200)
    app.aboutToQuit.connect(window.close)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
