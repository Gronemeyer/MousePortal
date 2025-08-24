from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
)
from PyQt6.QtCore import QProcess, Qt
import sys
import time
import json
import ast
import os

class PortalGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MousePortal Controller")

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)

        central = QWidget()
        layout = QVBoxLayout(central)
        self.cfg_path = "cfg.json"
        self.runtime_path = "cfg_runtime.json"
        self.table = QTableWidget()
        layout.addWidget(self.table)
        self.load_cfg()
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        self.launch_btn = QPushButton("Launch Portal")
        self.end_btn = QPushButton("End Portal")
        self.start_btn = QPushButton("Start Trial")
        self.stop_btn = QPushButton("Stop Trial")
        self.event_btn = QPushButton("Mark Event")

        layout.addWidget(self.launch_btn)
        layout.addWidget(self.end_btn)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.event_btn)

        self.launch_btn.clicked.connect(self.launch_process)
        self.end_btn.clicked.connect(self.end_process)
        self.start_btn.clicked.connect(lambda: self.send_cmd("start_trial"))
        self.stop_btn.clicked.connect(lambda: self.send_cmd("stop_trial"))
        self.event_btn.clicked.connect(lambda: self.send_cmd("mark_event button"))

        self.setCentralWidget(central)

    def load_cfg(self):
        with open(self.cfg_path, "r") as f:
            self.cfg = json.load(f)
        self.table.setRowCount(len(self.cfg))
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value"])
        for row, (key, val) in enumerate(self.cfg.items()):
            item_key = QTableWidgetItem(key)
            item_key.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, item_key)
            self.table.setItem(row, 1, QTableWidgetItem(str(val)))

    def gather_cfg(self):
        cfg = {}
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).text()
            val_text = self.table.item(row, 1).text()
            try:
                val = ast.literal_eval(val_text)
            except Exception:
                val = val_text
            cfg[key] = val
        return cfg

    def launch_process(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            cfg = self.gather_cfg()
            with open(self.runtime_path, "w") as f:
                json.dump(cfg, f, indent=2)
            self.process.start(sys.executable, ["runportal.py", "--dev", "--cfg", self.runtime_path])

    def end_process(self):
        if self.process.state() == QProcess.ProcessState.Running:
            self.send_cmd("end")
            self.process.waitForFinished(3000)
            if os.path.isfile(self.runtime_path):
                os.remove(self.runtime_path)

    def send_cmd(self, cmd: str) -> None:
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.write((cmd + f" {time.time()}\n").encode())

    def read_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode()
        if data:
            self.output.append(data.rstrip())

    def closeEvent(self, event):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.terminate()
            self.process.waitForFinished(3000)
        if os.path.isfile(self.runtime_path):
            os.remove(self.runtime_path)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    gui = PortalGUI()
    gui.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
