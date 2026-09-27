import subprocess
import sys

from squishy.workdir import claim_work_dir, sweep_stale


def test_live_instances_survive_each_others_sweep(tmp_path):
    a = claim_work_dir(tmp_path)
    (a.path / "upload.mp4").write_bytes(b"x")
    b = claim_work_dir(tmp_path)  # a second window on another port
    assert sweep_stale(tmp_path) == 0
    assert (a.path / "upload.mp4").exists() and b.path.is_dir()
    b.release()  # b quitting must not touch a
    assert (a.path / "upload.mp4").exists()
    assert not b.path.exists() and not b.lock_path.exists()
    a.release()
    assert not any(tmp_path.iterdir())


def test_dead_instance_is_swept(tmp_path):
    # A real process that claims a folder and is then killed: the OS closes its lock.
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; from pathlib import Path; from squishy.workdir import claim_work_dir; "
         "w = claim_work_dir(Path(sys.argv[1])); (w.path / 'up.mp4').write_bytes(b'x'); "
         "print(w.path, flush=True); time.sleep(60)", str(tmp_path)],
        stdout=subprocess.PIPE, text=True)
    try:
        path = child.stdout.readline().strip()
        assert path
        assert sweep_stale(tmp_path) == 0  # alive: held from another process
        assert (tmp_path / path / "up.mp4").exists()
    finally:
        child.kill()
        child.wait()
        child.stdout.close()
    assert sweep_stale(tmp_path) == 1
    assert not any(tmp_path.iterdir())


def test_sweep_removes_old_layout_files_and_unlocked_folders(tmp_path):
    (tmp_path / "abc123.mp4").write_bytes(b"x")  # v0.2.2 and earlier kept uploads here
    (tmp_path / "run-deadbeef").mkdir()  # its lock is gone
    live = claim_work_dir(tmp_path)
    assert sweep_stale(tmp_path) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([live.path.name, live.lock_path.name])
    live.release()


def test_sweep_of_missing_root_is_a_no_op(tmp_path):
    assert sweep_stale(tmp_path / "nope") == 0


def test_release_is_idempotent(tmp_path):
    w = claim_work_dir(tmp_path)
    w.release()
    w.release()
    assert not any(tmp_path.iterdir())
