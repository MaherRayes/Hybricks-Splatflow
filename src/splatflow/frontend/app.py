from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from splatflow.backend import PipelineConfig, SplatPipeline
from splatflow.backend.paths import AppPaths
from splatflow.backend.settings import Settings, SettingsStore, ToolPaths


def _forward_wheel_to_scrollarea(src: QtWidgets.QWidget, event: QtGui.QWheelEvent) -> None:
    # Find nearest parent scroll area (your options panel is inside one)
    w: QtWidgets.QWidget | None = src.parentWidget()
    scroll: QtWidgets.QAbstractScrollArea | None = None
    while w is not None:
        if isinstance(w, QtWidgets.QAbstractScrollArea):
            scroll = w
            break
        w = w.parentWidget()

    if scroll is not None:
        bar = scroll.verticalScrollBar()
        pixel = event.pixelDelta()
        if not pixel.isNull():
            bar.setValue(bar.value() - pixel.y())
        else:
            steps = event.angleDelta().y() / 120.0
            bar.setValue(bar.value() - int(steps * bar.singleStep() * 3))

    # Always consume so spinbox never sees it as "step value"
    event.accept()


class NoWheelSpinBox(QtWidgets.QSpinBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        le = self.lineEdit()
        if le is not None:
            le.installEventFilter(self)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        _forward_wheel_to_scrollarea(self, event)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Wheel:
            _forward_wheel_to_scrollarea(self, event)  # type: ignore[arg-type]
            return True
        return super().eventFilter(obj, event)


class NoWheelComboBox(QtWidgets.QComboBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.installEventFilter(self)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        _forward_wheel_to_scrollarea(self, event)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Wheel:
            _forward_wheel_to_scrollarea(self, event)  # type: ignore[arg-type]
            return True
        return super().eventFilter(obj, event)

class PipelineWorker(QtCore.QObject):
    log_line = QtCore.Signal(str)
    stage = QtCore.Signal(str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__()
        self.config = config

    @QtCore.Slot()
    def run(self) -> None:
        try:
            pipe = SplatPipeline()
            res = pipe.run(
                self.config,
                on_log=self.log_line.emit,
                on_stage=self.stage.emit,
            )
            self.finished.emit(res)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SplatFlow")
        self.setMinimumSize(980, 640)
        self.setStyleSheet(
            "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPushButton { min-height: 28px; }"
        )
        self.paths = AppPaths().ensure()
        self.settings_store = SettingsStore(self.paths)

        self._thread: QtCore.QThread | None = None
        self._worker: PipelineWorker | None = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        layout = QtWidgets.QHBoxLayout(central)

        form_container = QtWidgets.QWidget()
        form_container.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        form_col = QtWidgets.QVBoxLayout(form_container)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_container)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        layout.addWidget(scroll, 1)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        fixed = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.log.setFont(fixed)
        layout.addWidget(self.log, 2)

        # Input
        input_box = QtWidgets.QGroupBox("Input")
        form_col.addWidget(input_box)
        input_layout = QtWidgets.QFormLayout(input_box)
        input_layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        input_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.input_type = NoWheelComboBox()
        self.input_type.addItems(["images", "video"])
        input_layout.addRow("Type", self.input_type)

        self.input_path = QtWidgets.QLineEdit()
        browse_in = QtWidgets.QPushButton("Browse…")
        browse_in.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        browse_in.clicked.connect(self._browse_input)
        in_row = QtWidgets.QHBoxLayout()
        in_row.addWidget(self.input_path, 1)
        in_row.addWidget(browse_in)
        input_layout.addRow("Path", in_row)

        self.output_dir = QtWidgets.QLineEdit()
        browse_out = QtWidgets.QPushButton("Browse…")
        browse_out.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        browse_out.clicked.connect(self._browse_output)
        out_row = QtWidgets.QHBoxLayout()
        out_row.addWidget(self.output_dir, 1)
        out_row.addWidget(browse_out)
        input_layout.addRow("Output folder", out_row)

        # Tools
        tools_box = QtWidgets.QGroupBox("Tools")
        form_col.addWidget(tools_box)
        tools_layout = QtWidgets.QFormLayout(tools_box)
        tools_layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        tools_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.auto_install = QtWidgets.QCheckBox("Auto-install missing tools (recommended)")
        tools_layout.addRow("Auto-install", self.auto_install)

        self.colmap_path = QtWidgets.QLineEdit()
        colmap_browse = QtWidgets.QPushButton("Browse…")
        colmap_browse.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        colmap_browse.clicked.connect(lambda: self._browse_exe(self.colmap_path, "Select COLMAP executable"))
        colmap_row = QtWidgets.QHBoxLayout()
        colmap_row.addWidget(self.colmap_path, 1)
        colmap_row.addWidget(colmap_browse)
        tools_layout.addRow("COLMAP path (optional)", colmap_row)

        self.lichtfeld_path = QtWidgets.QLineEdit()
        lf_browse = QtWidgets.QPushButton("Browse…")
        lf_browse.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        lf_browse.clicked.connect(lambda: self._browse_exe(self.lichtfeld_path, "Select LichtFeld Studio executable"))
        lf_row = QtWidgets.QHBoxLayout()
        lf_row.addWidget(self.lichtfeld_path, 1)
        lf_row.addWidget(lf_browse)
        tools_layout.addRow("LichtFeld path (optional)", lf_row)

        # Basic settings
        basic_box = QtWidgets.QGroupBox("Basic settings")
        form_col.addWidget(basic_box)
        basic_layout = QtWidgets.QFormLayout(basic_box)
        basic_layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        basic_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        # Sharp Frames
        self.sf_enabled = QtWidgets.QCheckBox("Enable (required for video)")
        self.sf_enabled.setChecked(True)
        basic_layout.addRow("Frame sampling", self.sf_enabled)

        self.sf_method = NoWheelComboBox()
        self.sf_method.addItems(["best-n", "batched", "outlier-removal"])
        basic_layout.addRow("Sampling method", self.sf_method)

        self.sf_num_frames = NoWheelSpinBox()
        self.sf_num_frames.setRange(1, 50000)
        self.sf_num_frames.setValue(300)
        basic_layout.addRow("Target frames/images", self.sf_num_frames)

        self.sf_fps = NoWheelSpinBox()
        self.sf_fps.setRange(1, 240)
        self.sf_fps.setValue(10)
        basic_layout.addRow("Video FPS sampling", self.sf_fps)

        # COLMAP
        self.colmap_matcher = NoWheelComboBox()
        self.colmap_matcher.addItems(["exhaustive", "sequential"])
        basic_layout.addRow("COLMAP matcher", self.colmap_matcher)

        self.colmap_gpu = QtWidgets.QCheckBox("Use GPU if available")
        self.colmap_gpu.setChecked(True)
        basic_layout.addRow("COLMAP GPU", self.colmap_gpu)

        self.colmap_max_img = NoWheelSpinBox()
        self.colmap_max_img.setRange(800, 10000)
        self.colmap_max_img.setValue(3200)
        basic_layout.addRow("COLMAP max image size", self.colmap_max_img)

        # LichtFeld
        self.lfs_iters = NoWheelSpinBox()
        self.lfs_iters.setRange(1000, 2000000)
        self.lfs_iters.setValue(30000)
        basic_layout.addRow("LichtFeld iterations", self.lfs_iters)

        self.lfs_max_cap = NoWheelSpinBox()
        self.lfs_max_cap.setRange(10000, 50000000)
        self.lfs_max_cap.setValue(1_000_000)
        basic_layout.addRow("Max Gaussians", self.lfs_max_cap)

        self.lfs_strategy = NoWheelComboBox()
        self.lfs_strategy.addItems(["adc", "mcmc"])
        basic_layout.addRow("Strategy", self.lfs_strategy)

        # Advanced
        adv_box = QtWidgets.QGroupBox("Advanced settings")
        adv_box.setCheckable(True)
        adv_box.setChecked(False)
        form_col.addWidget(adv_box)
        adv_layout = QtWidgets.QFormLayout(adv_box)
        adv_layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        adv_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.sf_width = NoWheelSpinBox()
        self.sf_width.setRange(0, 8000)
        self.sf_width.setValue(0)
        adv_layout.addRow("Frame resize width (0 = keep)", self.sf_width)

        self.sf_format = NoWheelComboBox()
        self.sf_format.addItems(["jpg", "png"])
        adv_layout.addRow("Frame format", self.sf_format)

        self.sf_min_buffer = NoWheelSpinBox()
        self.sf_min_buffer.setRange(0, 100)
        self.sf_min_buffer.setValue(3)
        adv_layout.addRow("best-n: min_buffer", self.sf_min_buffer)

        self.sf_batch_size = NoWheelSpinBox()
        self.sf_batch_size.setRange(1, 200)
        self.sf_batch_size.setValue(5)
        adv_layout.addRow("batched: batch_size", self.sf_batch_size)

        self.sf_batch_buffer = NoWheelSpinBox()
        self.sf_batch_buffer.setRange(0, 100)
        self.sf_batch_buffer.setValue(2)
        adv_layout.addRow("batched: batch_buffer", self.sf_batch_buffer)

        self.sf_outlier_window = NoWheelSpinBox()
        self.sf_outlier_window.setRange(1, 500)
        self.sf_outlier_window.setValue(15)
        adv_layout.addRow("outlier: window_size", self.sf_outlier_window)

        self.sf_outlier_sens = NoWheelSpinBox()
        self.sf_outlier_sens.setRange(0, 100)
        self.sf_outlier_sens.setValue(50)
        adv_layout.addRow("outlier: sensitivity", self.sf_outlier_sens)

        self.colmap_camera_model = NoWheelComboBox()
        self.colmap_camera_model.addItems(
            [
                "PINHOLE",
                "SIMPLE_PINHOLE",
                "SIMPLE_RADIAL",
                "RADIAL",
                "OPENCV",
                "FULL_OPENCV",
                "OPENCV_FISHEYE",
                "FOV",
                "SIMPLE_RADIAL_FISHEYE",
                "RADIAL_FISHEYE",
                "THIN_PRISM_FISHEYE",
            ]
        )
        self.colmap_camera_model.setCurrentText("PINHOLE")
        adv_layout.addRow("COLMAP camera model", self.colmap_camera_model)

        self.colmap_single_cam = QtWidgets.QCheckBox("Treat as single camera")
        self.colmap_single_cam.setChecked(True)
        adv_layout.addRow("COLMAP single camera", self.colmap_single_cam)

        self.colmap_sift_features = NoWheelSpinBox()
        self.colmap_sift_features.setRange(1024, 50000)
        self.colmap_sift_features.setValue(8192)
        adv_layout.addRow("COLMAP max SIFT features", self.colmap_sift_features)

        self.colmap_seq_overlap = NoWheelSpinBox()
        self.colmap_seq_overlap.setRange(1, 50)
        self.colmap_seq_overlap.setValue(10)
        adv_layout.addRow("COLMAP sequential overlap", self.colmap_seq_overlap)

        self.lfs_resize = NoWheelComboBox()
        self.lfs_resize.addItems(["auto", "1", "2", "4", "8"])
        self.lfs_resize.setCurrentText("auto")
        adv_layout.addRow("LichtFeld resize_factor", self.lfs_resize)

        self.lfs_eval = QtWidgets.QCheckBox("Run evaluation during training")
        self.lfs_eval.setChecked(False)
        adv_layout.addRow("LichtFeld eval", self.lfs_eval)

        self.lfs_gut = QtWidgets.QCheckBox("Enable GUT")
        self.lfs_gut.setChecked(False)
        adv_layout.addRow("LichtFeld GUT", self.lfs_gut)

        self.lfs_ppisp = QtWidgets.QCheckBox("Enable PPISP")
        self.lfs_ppisp.setChecked(False)
        adv_layout.addRow("LichtFeld PPISP", self.lfs_ppisp)

        self.lfs_mip = QtWidgets.QCheckBox("Enable MIP filtering")
        self.lfs_mip.setChecked(False)
        adv_layout.addRow("LichtFeld MIP", self.lfs_mip)

        self.lfs_save_eval = QtWidgets.QCheckBox("Save evaluation images")
        self.lfs_save_eval.setChecked(False)
        adv_layout.addRow("LichtFeld save eval images", self.lfs_save_eval)

        self.lfs_test_every = NoWheelSpinBox()
        self.lfs_test_every.setRange(1, 1000)
        self.lfs_test_every.setValue(8)
        adv_layout.addRow("LichtFeld test_every", self.lfs_test_every)

        self.keep_intermediates = QtWidgets.QCheckBox("Keep intermediate files")
        self.keep_intermediates.setChecked(True)
        adv_layout.addRow("Workspace", self.keep_intermediates)

        # Actions
        btn_row = QtWidgets.QHBoxLayout()
        form_col.addLayout(btn_row)
        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)

        self.open_btn = QtWidgets.QPushButton("Open output")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output)
        btn_row.addWidget(self.open_btn)

        btn_row.addStretch(1)

        self._last_output: Path | None = None

        self.input_type.currentTextChanged.connect(self._sync_defaults)
        self._sync_defaults()
        self._load_settings()


    def _load_settings(self) -> None:
        s = self.settings_store.load()
        self.auto_install.setChecked(bool(s.auto_install_tools))
        self.colmap_path.setText(s.tool_paths.colmap or "")
        self.lichtfeld_path.setText(s.tool_paths.lichtfeld or "")

    def _save_settings(self) -> None:
        colmap = self.colmap_path.text().strip() or None
        lf = self.lichtfeld_path.text().strip() or None
        s = self.settings_store.load()
        s.auto_install_tools = self.auto_install.isChecked()
        s.tool_paths = ToolPaths(colmap=colmap, lichtfeld=lf)
        self.settings_store.save(s)

    def _sync_defaults(self) -> None:
        t = self.input_type.currentText()
        if t == "video":
            self.sf_enabled.setChecked(True)
            self.colmap_matcher.setCurrentText("sequential")
        else:
            self.colmap_matcher.setCurrentText("exhaustive")

    def _browse_input(self) -> None:
        t = self.input_type.currentText()
        if t == "images":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select images folder")
            if path:
                self.input_path.setText(path)
        else:
            m = QtWidgets.QMessageBox(self)
            m.setWindowTitle("Select input")
            m.setText("Choose a single video file, or a folder containing multiple videos.")
            file_btn = m.addButton("Single file…", QtWidgets.QMessageBox.AcceptRole)
            dir_btn = m.addButton("Folder…", QtWidgets.QMessageBox.AcceptRole)
            m.addButton(QtWidgets.QMessageBox.Cancel)
            m.exec()

            clicked = m.clickedButton()
            if clicked == file_btn:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, "Select video file", filter="Video files (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;All files (*)"
                )
            elif clicked == dir_btn:
                path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder with videos")
            else:
                return
            if path:
                self.input_path.setText(path)

    def _browse_output(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_dir.setText(path)


    def _browse_exe(self, target: QtWidgets.QLineEdit, title: str) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, filter="Executable (*)")
        if path:
            target.setText(path)

    def _build_config(self) -> PipelineConfig:
        input_type = self.input_type.currentText()
        input_path = self.input_path.text().strip()
        output_dir = self.output_dir.text().strip()

        cfg = PipelineConfig.defaults(input_type=input_type, input_path=input_path, output_dir=output_dir)

        cfg.frame_sampling.enabled = self.sf_enabled.isChecked()
        cfg.frame_sampling.selection_method = self.sf_method.currentText()
        cfg.frame_sampling.num_frames = int(self.sf_num_frames.value())
        cfg.frame_sampling.fps = int(self.sf_fps.value())
        cfg.frame_sampling.width = int(self.sf_width.value())
        cfg.frame_sampling.format = self.sf_format.currentText()

        cfg.frame_sampling.min_buffer = int(self.sf_min_buffer.value())
        cfg.frame_sampling.batch_size = int(self.sf_batch_size.value())
        cfg.frame_sampling.batch_buffer = int(self.sf_batch_buffer.value())
        cfg.frame_sampling.outlier_window_size = int(self.sf_outlier_window.value())
        cfg.frame_sampling.outlier_sensitivity = int(self.sf_outlier_sens.value())

        cfg.colmap.matcher = self.colmap_matcher.currentText()
        cfg.colmap.use_gpu = self.colmap_gpu.isChecked()
        cfg.colmap.max_image_size = int(self.colmap_max_img.value())
        cfg.colmap.camera_model = self.colmap_camera_model.currentText() or "PINHOLE"
        cfg.colmap.single_camera = self.colmap_single_cam.isChecked()

        cfg.colmap.sift_max_num_features = int(self.colmap_sift_features.value())
        cfg.colmap.sequential_overlap = int(self.colmap_seq_overlap.value())

        cfg.lichtfeld.iterations = int(self.lfs_iters.value())
        cfg.lichtfeld.max_cap = int(self.lfs_max_cap.value())
        cfg.lichtfeld.strategy = self.lfs_strategy.currentText()
        cfg.lichtfeld.resize_factor = self.lfs_resize.currentText()

        cfg.lichtfeld.eval = self.lfs_eval.isChecked()
        cfg.lichtfeld.save_eval_images = self.lfs_save_eval.isChecked()
        cfg.lichtfeld.test_every = int(self.lfs_test_every.value())

        cfg.lichtfeld.gut = self.lfs_gut.isChecked()
        cfg.lichtfeld.ppisp_controller = self.lfs_ppisp.isChecked()
        cfg.lichtfeld.mip_filter = self.lfs_mip.isChecked()

        cfg.output.keep_intermediates = self.keep_intermediates.isChecked()
        return cfg

    def _start(self) -> None:
        self.open_btn.setEnabled(False)
        self._last_output = None

        self._save_settings()
        cfg = self._build_config()
        self.log.clear()
        self._append("Starting…")

        thread = QtCore.QThread(self)
        worker = PipelineWorker(cfg)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_line.connect(self._append)
        worker.stage.connect(lambda s: self._append(f"\n## {s}"))
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        self.start_btn.setEnabled(False)
        thread.start()

    def _on_finished(self, result: object) -> None:
        self.start_btn.setEnabled(True)
        try:
            out = getattr(result, "output_dir", None)
            if out:
                self._last_output = Path(out)
                self.open_btn.setEnabled(True)
        finally:
            self._append("\nFinished.")

    def _on_failed(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Pipeline failed", message)
        self._append("\nFAILED: " + message)

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)

    def _open_output(self) -> None:
        if not self._last_output:
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._last_output)))


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())