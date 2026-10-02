"""Real Qt folder-panel ownership, with generated temporary hierarchies."""
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'taggui'))
from widgets import folder_tree_panel
from utils.latest_task import LatestTask

APP = QApplication.instance() or QApplication([])


def pump(predicate, seconds=4):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:
        APP.processEvents()
        time.sleep(.002)
    assert predicate()


def create_panel():
    main=QMainWindow()
    main._active_directory_browser_name=lambda:'primary'
    main._supported_external_drop_suffixes=lambda:{'.png'}
    main.directory_path=None
    main.setCentralWidget(QWidget())
    panel=folder_tree_panel.FolderTreePanel(main)
    main.addDockWidget(Qt.LeftDockWidgetArea,panel)
    return main,panel


def test_hidden_tree_defers_scan_and_latest_root_wins(tmp_path,monkeypatch):
    first,second=tmp_path/'first',tmp_path/'second'
    first.mkdir();second.mkdir()
    (second/'child').mkdir()
    (second/'child'/'image.png').touch()
    calls=[]
    started,release=threading.Event(),threading.Event()
    original=folder_tree_panel.collect_folder_snapshot
    def snapshot(payload,cancelled):
        calls.append(payload[0])
        if payload[0]==first:
            started.set()
            assert release.wait(2)
        return original(payload,cancelled)
    monkeypatch.setattr(folder_tree_panel,'collect_folder_snapshot',snapshot)
    main,panel=create_panel()
    try:
        panel.set_root(first)
        APP.processEvents()
        assert calls==[]
        main.show()
        pump(started.is_set)
        panel.set_root(second)
        release.set()
        pump(lambda:panel.tree.isEnabled() and panel.tree.topLevelItemCount()==1
             and panel.tree.topLevelItem(0).text(0)=='second')
        root=panel.tree.topLevelItem(0)
        assert root.text(1)=='1' and root.childCount()==1
        assert panel.selected_path()==second
        assert calls==[first,second]
    finally:
        release.set()
        panel._tree_task.drain();panel._tree_task.close()
        main.close()
        main.deleteLater()
        APP.processEvents()


def test_large_tree_population_yields_to_qt_events(tmp_path,monkeypatch):
    # A snapshot has no filesystem or Qt objects; only installation is timed.
    rows=[(tmp_path,None,0,False)]
    rows.extend((tmp_path/f'child-{i}',0,0,False) for i in range(3000))
    monkeypatch.setattr(folder_tree_panel,'collect_folder_snapshot',lambda *_:tuple(rows))
    main,panel=create_panel()
    ticks=[]
    timer=QTimer()
    timer.timeout.connect(lambda:ticks.append(panel.tree.topLevelItemCount()))
    timer.start(1)
    try:
        main.show()
        panel.set_root(tmp_path)
        pump(lambda:panel.tree.topLevelItemCount()==1 and panel.tree.isEnabled()
             and panel.tree.topLevelItem(0).childCount()==3000)
        assert len(ticks)>1
    finally:
        timer.stop()
        panel._tree_task.drain();panel._tree_task.close()
        main.close();main.deleteLater()
        APP.processEvents()


def test_relocation_drains_new_file_readers_before_rename(tmp_path):
    root=tmp_path/'generated-root'
    root.mkdir()
    (root/'media.bin').write_bytes(b'generated')
    started=threading.Event()
    task=LatestTask()
    released=[]
    def hold_media(payload,cancelled):
        with (root/'media.bin').open('rb'):
            started.set()
            assert cancelled.wait(2)
        released.append(True)
    main,panel=create_panel()
    main.image_list_model=SimpleNamespace(quiesce_ordered_view=task.drain)
    delivered=[]
    task.completed.connect(lambda *args:delivered.append(args))
    try:
        task.submit(hold_media,None)
        assert started.wait(1)
        panel._quiesce_auxiliary_readers()
        assert released==[True]
        root.rename(tmp_path/'renamed-root')
        APP.processEvents()
        assert delivered==[]
    finally:
        task.drain();task.close();panel._tree_task.close()
        main.close();main.deleteLater()
        APP.processEvents()
