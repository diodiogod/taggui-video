import gc
from pathlib import Path
import sys
import threading
import weakref

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.media_file_lock import get_media_file_lock, synchronized_media_file


def test_waiting_operation_keeps_shared_lock_alive(tmp_path):
    path=tmp_path/'image.png'
    lock=get_media_file_lock(path)
    reference=weakref.ref(lock)
    waiting,finished=threading.Event(),threading.Event()
    seen=[]
    def wait():
        retained=get_media_file_lock(path)
        seen.append(retained is reference())
        waiting.set()
        with retained:
            finished.set()
    lock.acquire()
    worker=threading.Thread(target=wait)
    worker.start()
    assert waiting.wait(1)
    gc.collect()
    assert get_media_file_lock(path) is lock
    assert not finished.is_set()
    lock.release()
    del lock
    worker.join(1)
    assert finished.is_set() and seen==[True]
    gc.collect()
    assert reference() is None


def test_completed_file_operations_do_not_retain_every_path(tmp_path):
    references=[]
    @synchronized_media_file
    def operation(path):
        lock=get_media_file_lock(path)
        references.append(weakref.ref(lock))
        with lock:  # Reentrancy and shared identity remain supported.
            return True
    for i in range(1000):
        assert operation(tmp_path/f'{i}.png')
    gc.collect()
    assert all(reference() is None for reference in references)
