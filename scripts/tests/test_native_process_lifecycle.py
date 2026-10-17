from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import native_process_lifecycle as lifecycle  # noqa: E402


@unittest.skipUnless(
    sys.platform == "darwin",
    "macOS proc identity and NOTE_EXIT fixtures run in iOS native qualification",
)
class NativeProcessLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-process-lifecycle-")
        self.root = Path(self.temporary.name)
        self.source_root = self.root / "source"
        self.source_root.mkdir()
        (self.source_root / "source.txt").write_text("fixture source\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.source_root, check=True)
        subprocess.run(["git", "add", "source.txt"], cwd=self.source_root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"],
            cwd=self.source_root,
            check=True,
        )
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.calls_file = self.root / "fake-tool-calls.log"
        self.environment_file = self.root / "fake-tool-environment.json"
        self.ibtool = self.tools / "ibtool"
        self.ibtool.write_text(
            f"#!{sys.executable}\n"
            "import json, os, shutil, sys\n"
            "import time\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "time.sleep(.1)\n"
            "calls = os.environ.get('NATIVE_TEST_CALLS')\n"
            "if calls:\n"
            "    with open(calls, 'a', encoding='utf-8') as stream: stream.write(' '.join(args) + '\\n')\n"
            "environment = {'IBTOOLNEVERDEQUE': os.environ.get('IBTOOLNEVERDEQUE'), 'IBTOOLD-SECRET': os.environ.get('IBTOOLD-SECRET')}\n"
            "target = os.environ.get('NATIVE_TEST_ENVIRONMENT')\n"
            "if target:\n"
            "    Path(target).write_text(json.dumps(environment), encoding='utf-8')\n"
            "if os.environ.get('NATIVE_TEST_FAIL_COMPILE') == '1' and '--compile' in args: sys.exit(17)\n"
            "if '--compile' in args:\n"
            "    output = Path(args[args.index('--compile') + 1])\n"
            "    output.mkdir(parents=True, exist_ok=True)\n"
            "    (output / 'compiled.txt').write_text('compiled storyboard\\n', encoding='utf-8')\n"
            "elif '--link' in args:\n"
            "    output = Path(args[args.index('--link') + 1])\n"
            "    source = Path(args[-1])\n"
            "    output.mkdir(parents=True, exist_ok=True)\n"
            "    destination = output / source.name\n"
            "    if destination.exists(): shutil.rmtree(destination)\n"
            "    shutil.copytree(source, destination)\n"
            "print('fake ibtool completed')\n",
            encoding="utf-8",
        )
        self.ibtool.chmod(0o700)
        self.ibtoold = Path(sys.executable).resolve(strict=True)
        self.specs = {
            "compiler": self.tools / "IBCompiler.xcspec",
            "storyboard_compiler": self.tools / "IBStoryboardCompiler.xcspec",
            "linker": self.tools / "IBStoryboardLinker.xcspec",
            "postprocessor": self.tools / "IBPostprocessor.xcspec",
        }
        self.specs["compiler"].write_text('CommandLine = "$(IBC_EXEC)";\n', encoding="utf-8")
        self.specs["storyboard_compiler"].write_text('CommandLine = "$(IBC_EXEC) --compile";\n', encoding="utf-8")
        self.specs["linker"].write_text('CommandLine = "$(IBC_EXEC) --link";\n', encoding="utf-8")
        self.specs["postprocessor"].write_text('CommandLine = "ibtool [options]";\n', encoding="utf-8")
        self.invocation_dir, self.binding_path, self.wrapper_path = self._create_invocation()
        lifecycle.write_wrapper(self.binding_path, self.wrapper_path, sys.executable)
        self.stop_files: list[Path] = []
        self.kqueues = []
        self.writer_pids: list[int] = []

    def tearDown(self):
        for stop in self.stop_files:
            stop.touch(exist_ok=True)
        for kqueue in self.kqueues:
            kqueue.close()
        self.temporary.cleanup()

    def _create_invocation(
        self,
        *,
        evidence: Path | None = None,
        worktree_root: Path | None = None,
        assignment_guard: dict[str, str] | None = None,
    ):
        evidence = evidence or self.evidence
        evidence.mkdir(parents=True, exist_ok=True)
        return lifecycle.create_invocation(
            evidence_dir=evidence,
            source_root=self.source_root,
            qualifier_pid=os.getpid(),
            worktree_root=worktree_root or (self.root / "not-created-worktree"),
            derived_data_root=self.root / "DerivedData",
            harness_root=self.root / "harness-bin",
            ibtool_path=self.ibtool,
            ibtoold_path=self.ibtoold,
            xcodebuild_path=Path(sys.executable).resolve(strict=True),
            developer_dir=Path(os.environ.get("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")).resolve(strict=True),
            xcode_version="fixture-27.1",
            xcode_build="fixture-27A9275",
            spec_paths=self.specs,
            helper_path=ROOT / "scripts" / "lib" / "native_process_lifecycle.py",
            qualifier_script_path=ROOT / "scripts" / "ios-native-qualification.sh",
            assignment_guard=assignment_guard,
        )

    def _run_cli(self, *, stage: str, argv: list[str], timeout: float = 5.0, env: dict[str, str] | None = None):
        call_id = f"test-{stage}-{time.monotonic_ns()}"
        record_path = self.invocation_dir / "records" / f"{call_id}.record.json"
        stdout_path = self.invocation_dir / "records" / f"{call_id}.stdout.log"
        stderr_path = self.invocation_dir / "records" / f"{call_id}.stderr.log"
        environment = os.environ.copy()
        environment.update(
            NATIVE_TEST_CALLS=str(self.calls_file),
            NATIVE_TEST_ENVIRONMENT=str(self.environment_file),
        )
        if env:
            environment.update(env)
        command = [
            sys.executable,
            str(ROOT / "scripts" / "lib" / "native_process_lifecycle.py"),
            "run",
            "--record",
            str(record_path),
            "--invocation-record",
            str(self.binding_path),
            "--stage",
            stage,
            "--cwd",
            str(self.root),
            "--stdout",
            str(stdout_path),
            "--stderr",
            str(stderr_path),
            "--timeout-seconds",
            str(timeout),
            "--",
            *argv,
        ]
        result = subprocess.run(command, cwd=self.source_root, env=environment, capture_output=True, text=True, check=False)
        self.assertTrue(record_path.is_file(), result.stderr)
        return result, json.loads(record_path.read_text(encoding="utf-8")), stdout_path, stderr_path

    def _run_wrapper(self, argv: list[str], *, environment: dict[str, str] | None = None):
        env = os.environ.copy()
        env.update(NATIVE_TEST_CALLS=str(self.calls_file), NATIVE_TEST_ENVIRONMENT=str(self.environment_file))
        if environment:
            env.update(environment)
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "lib" / "native_process_lifecycle.py"), "ibtool-wrapper", "--binding", str(self.binding_path), "--", *argv],
            cwd=self.source_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _start_gated_writer(self, *, detached: bool, binding_path: Path | None = None):
        binding_path = binding_path or self.binding_path
        output_root = self.root / ("detached-writer-root" if detached else "same-session-writer-root")
        output_root.mkdir()
        gate = self.root / ("detached-writer-go" if detached else "same-session-writer-go")
        stop = self.root / ("detached-writer-stop" if detached else "same-session-writer-stop")
        pid_file = self.root / ("detached-writer-pid" if detached else "same-session-writer-pid")
        self.stop_files.append(stop)
        writer_code = (
            "import pathlib,sys,time\n"
            "root,gate,stop=map(pathlib.Path,sys.argv[1:])\n"
            "while not gate.exists(): time.sleep(.01)\n"
            "path=root/'writes.log'\n"
            "with path.open('a',encoding='utf-8') as out:\n"
            "  while not stop.exists(): out.write('writer-active\\n'); out.flush(); time.sleep(.02)\n"
        )
        parent_code = (
            "import pathlib,subprocess,sys\n"
            "pid_file,root,gate,stop,detached,writer=sys.argv[1:]\n"
            "child=subprocess.Popen([sys.executable,'-c',writer,root,gate,stop],start_new_session=(detached=='1'),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)\n"
            "pathlib.Path(pid_file).write_text(str(child.pid),encoding='utf-8')\n"
        )
        subprocess.run(
            [sys.executable, "-c", parent_code, str(pid_file), str(output_root), str(gate), str(stop), "1" if detached else "0", writer_code],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        pid = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 5
        identity = None
        while time.monotonic() < deadline:
            identity = lifecycle.process_identity(pid)
            if identity is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(identity, "fixture writer never became observable")
        kqueue = lifecycle._register_note_exit(pid, identity["birth"])
        self.kqueues.append(kqueue)
        lifecycle._record_known_child(
            binding_path,
            pid,
            identity["birth"],
            label="detached-writer" if detached else "same-session-writer",
            evidence_path=str(output_root),
        )
        gate.touch()
        deadline = time.monotonic() + 5
        writes = output_root / "writes.log"
        while not writes.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(writes.exists(), "fixture writer did not begin appending")
        self.writer_pids.append(pid)
        return pid, identity["birth"], kqueue, output_root, writes, stop

    def test_success_records_actual_child_exit(self):
        code = "import os; print(os.getcwd() + ':' + os.environ['NATIVE_LIFECYCLE_TEST'])"
        result, record, stdout, stderr = self._run_cli(
            stage="simple-child",
            argv=[sys.executable, "-c", code],
            env={"NATIVE_LIFECYCLE_TEST": "selected-input"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["child_exit"], 0)
        self.assertIsNotNone(record["process"]["birth"])
        self.assertEqual(stdout.read_text(encoding="utf-8").strip(), f"{self.root}:selected-input")
        self.assertTrue(stderr.is_file())
        supplied_records = list((self.invocation_dir / "records").glob("*.record.json"))
        self.assertEqual(lifecycle.verify_invocation(self.binding_path, supplied_records)["status"], "PASS")

    def test_missing_executable_has_null_child_exit(self):
        missing = self.root / "does-not-exist"
        result, record, _, stderr = self._run_cli(stage="missing", argv=[str(missing)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(record["child_exit"])
        self.assertIn("FileNotFoundError", record["launch_error"])
        self.assertIn("FileNotFoundError", stderr.read_text(encoding="utf-8"))

    def test_nonexecutable_has_null_child_exit(self):
        blocked = self.root / "not-executable"
        blocked.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        blocked.chmod(0o600)
        result, record, _, stderr = self._run_cli(stage="nonexecutable", argv=[str(blocked)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(record["child_exit"])
        self.assertIn("PermissionError", record["launch_error"])
        self.assertIn("PermissionError", stderr.read_text(encoding="utf-8"))

    def test_timeout_retains_live_root(self):
        output_root = self.root / "live-output-root"
        output_root.mkdir()
        stop = self.root / "live-output-stop"
        self.stop_files.append(stop)
        code = (
            "import pathlib,sys,time\n"
            "root,stop=map(pathlib.Path,sys.argv[1:])\n"
            "with (root/'writes.log').open('a',encoding='utf-8') as out:\n"
            "  while not stop.exists(): out.write('still-writing\\n'); out.flush(); time.sleep(.03)\n"
        )
        root_inode = output_root.stat().st_ino
        result, record, _, _ = self._run_cli(stage="timed-child", argv=[sys.executable, "-c", code, str(output_root), str(stop)], timeout=0.2)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(record["timed_out"])
        self.assertIsNone(record["child_exit"])
        self.assertFalse(record["outputs_complete"])
        pid = record["process"]["pid"]
        self.assertEqual(lifecycle.process_identity(pid)["birth"], record["process"]["birth"])
        first_size = (output_root / "writes.log").stat().st_size
        time.sleep(0.1)
        self.assertGreater((output_root / "writes.log").stat().st_size, first_size)
        self.assertEqual(output_root.stat().st_ino, root_inode)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "KNOWN_CHILD_STILL_LIVE|PROCESS_RESULT_INCOMPLETE"):
            lifecycle.verify_invocation(self.binding_path)
        stop.touch()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and lifecycle.process_identity(pid) is not None:
            time.sleep(0.05)
        self.assertIsNone(lifecycle.process_identity(pid), "timeout fixture did not exit naturally")

    def test_ibtool_wrapper_records_effective_direct_execution(self):
        environment = os.environ.copy()
        environment["IBTOOLD-SECRET"] = "must-not-reach-child"
        environment["NATIVE_TEST_CALLS"] = str(self.calls_file)
        environment["NATIVE_TEST_ENVIRONMENT"] = str(self.environment_file)
        result = self._run_wrapper(["--version"], environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = sorted((self.invocation_dir / "records").glob("*.record.json"))
        record = json.loads(records[-1].read_text(encoding="utf-8"))
        self.assertEqual(record["stage"], "version")
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["child_exit"], 0)
        self.assertEqual(record["exec_transition"]["executable"], str(self.ibtoold))
        self.assertEqual(record["process"]["pid"], record["exec_transition"]["pid"])
        self.assertEqual(record["process"]["birth"], record["exec_transition"]["birth"])
        self.assertEqual(record["environment_allowlist"]["IBTOOLNEVERDEQUE"], "1")
        self.assertNotIn("IBTOOLD-SECRET", record["environment_allowlist"])
        observed = json.loads(self.environment_file.read_text(encoding="utf-8"))
        self.assertEqual(observed, {"IBTOOLNEVERDEQUE": "1", "IBTOOLD-SECRET": None})

    def test_capability_failure_has_no_pooled_fallback(self):
        lifecycle.record_phase(self.binding_path, "capability-required")
        storyboard = self.root / "SplashScreen.storyboard"
        storyboard.write_text("<document type='com.apple.InterfaceBuilder3.CocoaTouch.Storyboard.XIB'/>\n", encoding="utf-8")
        output = self.invocation_dir / "capability-failure"
        environment = os.environ.copy()
        environment.update(NATIVE_TEST_CALLS=str(self.calls_file), NATIVE_TEST_FAIL_COMPILE="1")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "lib" / "native_process_lifecycle.py"), "capability", "--binding", str(self.binding_path), "--storyboard", str(storyboard), "--output-dir", str(output)],
            cwd=self.source_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        proof = json.loads((self.invocation_dir / "capability-proof.json").read_text(encoding="utf-8"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(proof["status"], "FAILURE")
        self.assertEqual(proof["fallback"], "none")
        self.assertEqual([entry["stage"] for entry in proof["calls"]], ["capability-compile"])
        self.assertEqual(self.calls_file.read_text(encoding="utf-8").count("--compile"), 1)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "PROCESS_RESULT_INCOMPLETE|CAPABILITY_PROOF_MISSING_OR_FAILED"):
            lifecycle.verify_invocation(self.binding_path)

    def test_shared_service_untouched(self):
        stop = self.root / "shared-service-stop"
        marker = self.root / "shared-service-output"
        self.stop_files.append(stop)
        code = (
            "import pathlib,sys,time\n"
            "stop,marker=map(pathlib.Path,sys.argv[1:])\n"
            "with marker.open('a',encoding='utf-8') as out:\n"
            "  while not stop.exists(): out.write('alive\\n'); out.flush(); time.sleep(.03)\n"
        )
        service = subprocess.Popen([sys.executable, "-c", code, str(stop), str(marker)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        identity = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            identity = lifecycle.process_identity(service.pid)
            if identity is not None and marker.exists():
                break
            time.sleep(0.01)
        self.assertIsNotNone(identity)
        result = lifecycle.verify_invocation(self.binding_path)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(lifecycle.process_identity(service.pid)["birth"], identity["birth"])
        self.assertFalse(stop.exists())
        stop.touch()
        self.assertEqual(service.wait(timeout=5), 0)

    def test_fullbuild_propagation_requires_compile_and_link_records(self):
        lifecycle.record_phase(self.binding_path, "capability-required")
        storyboard = self.root / "generated" / "SplashScreen.storyboard"
        storyboard.parent.mkdir()
        storyboard.write_text("<document type='com.apple.InterfaceBuilder3.CocoaTouch.Storyboard.XIB'/>\n", encoding="utf-8")
        cap_output = self.invocation_dir / "capability"
        code, cap_record = lifecycle.run_capability(self.binding_path, storyboard, cap_output)
        self.assertEqual(code, 0, cap_record)
        compile_output = self.root / "DerivedData" / "Build" / "Intermediates" / "SplashScreen.storyboardc"
        compile_output.parent.mkdir(parents=True)
        compiled_result = self._run_wrapper(["--compile", str(compile_output), str(storyboard)])
        self.assertEqual(compiled_result.returncode, 0, compiled_result.stderr)
        build_invocation = self.evidence / "build-invocation.json"
        build_invocation.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "executable": str(Path(sys.executable).resolve()),
                    "argv": [f"IBC_EXEC={self.wrapper_path}"],
                    "interface_builder": {"IBC_EXEC": str(self.wrapper_path)},
                }
            ),
            encoding="utf-8",
        )
        build_log = self.evidence / "xcodebuild.log"
        build_log.write_text(
            f"CompileStoryboard {storyboard} (in target 'NutritionApp')\n"
            "LinkStoryboards /fixture/NutritionApp.app (in target 'NutritionApp')\n",
            encoding="utf-8",
        )
        missing_link = self.evidence / "missing-link-build-invocation.json"
        missing_link.write_text(build_invocation.read_text(encoding="utf-8"), encoding="utf-8")
        app_product = self.root / "DerivedData" / "Build" / "Products" / "NutritionApp.app"
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_IB_RECORD_COUNT_MISMATCH"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=missing_link,
                build_log_path=build_log,
                app_product_path=app_product,
            )
        build_output = app_product / "Resources"
        build_output.mkdir(parents=True)
        linked = self._run_wrapper(["--link", str(build_output), str(compile_output)])
        self.assertEqual(linked.returncode, 0, linked.stderr)
        app_product.mkdir(parents=True, exist_ok=True)
        lifecycle.write_full_build_proof(
            self.binding_path,
            build_invocation_path=build_invocation,
            build_log_path=build_log,
            app_product_path=app_product,
        )
        lifecycle.record_phase(self.binding_path, "xcode-build-started")
        self.assertEqual(lifecycle.verify_invocation(self.binding_path)["status"], "PASS")
        proof_path = self.invocation_dir / "full-build-proof.json"
        proof_bytes = proof_path.read_bytes()
        proof = json.loads(proof_bytes)
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["xcode_tasks"]["compile_count"], 1)
        self.assertEqual(proof["xcode_tasks"]["link_count"], 1)
        proof["wrapper"] = str(self.root / "stale-wrapper")
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "FULL_BUILD_WRAPPER_BINDING_MISMATCH"):
            lifecycle.verify_invocation(self.binding_path)
        proof_path.write_bytes(proof_bytes)
        record_path = next(
            path for path in (self.invocation_dir / "records").glob("*.record.json")
            if json.loads(path.read_text(encoding="utf-8")).get("stage") == "compile"
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["exec_transition"]["sha256"] = "0" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "FULL_BUILD_IB_RECORD_INVALID"):
            lifecycle.verify_invocation(self.binding_path)

    def test_missing_or_unmatched_ib_record_blocks_cleanup(self):
        lifecycle.record_phase(self.binding_path, "capability-required")
        storyboard = self.root / "SplashScreen.storyboard"
        storyboard.write_text("<document type='storyboard'/>\n", encoding="utf-8")
        result, _ = lifecycle.run_capability(self.binding_path, storyboard, self.invocation_dir / "capability")
        self.assertEqual(result, 0)
        lifecycle.record_phase(self.binding_path, "xcode-build-started")
        output_root = self.root / "unmatched-output-root"
        output_root.mkdir()
        with self.assertRaisesRegex(lifecycle.LifecycleError, "FULL_BUILD_PROOF_MISSING"):
            lifecycle.verify_invocation(self.binding_path)
        self.assertTrue(output_root.is_dir())

    def test_same_session_writer_blocks_cleanup(self):
        self._assert_writer_blocks_cleanup(detached=False)

    def test_detached_writer_blocks_cleanup(self):
        self._assert_writer_blocks_cleanup(detached=True)

    def _assert_writer_blocks_cleanup(self, *, detached: bool):
        pid, birth, kqueue, output_root, writes, stop = self._start_gated_writer(detached=detached)
        root_identity = output_root.stat().st_ino
        first_size = writes.stat().st_size
        time.sleep(0.1)
        self.assertGreater(writes.stat().st_size, first_size)
        move_events = []
        with self.assertRaisesRegex(lifecycle.LifecycleError, f"KNOWN_CHILD_STILL_LIVE:{pid}"):
            lifecycle.verify_invocation(self.binding_path)
        self.assertEqual(move_events, [])
        self.assertTrue(output_root.is_dir())
        self.assertEqual(output_root.stat().st_ino, root_identity)
        stop.touch()
        lifecycle._record_known_child_exit(self.binding_path, pid, birth, kqueue)
        self.assertEqual(lifecycle.verify_invocation(self.binding_path)["status"], "PASS")

    def test_observation_unavailable_retains(self):
        pid, birth, kqueue, output_root, _, stop = self._start_gated_writer(detached=False)
        original_identity = lifecycle.process_identity

        def unavailable(candidate):
            if candidate == pid:
                raise lifecycle.LifecycleError("simulated unavailable process observation")
            return original_identity(candidate)

        with patch.object(lifecycle, "process_identity", side_effect=unavailable):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "KNOWN_CHILD_OBSERVATION_UNAVAILABLE"):
                lifecycle.verify_invocation(self.binding_path)
        self.assertTrue(output_root.is_dir())
        stop.touch()
        lifecycle._record_known_child_exit(self.binding_path, pid, birth, kqueue)

    def test_pid_birth_change_refuses(self):
        pid, birth, kqueue, output_root, _, stop = self._start_gated_writer(detached=False)
        marker = next((self.invocation_dir / "records").glob("known-*.started.json"))
        started = json.loads(marker.read_text(encoding="utf-8"))
        started["child_birth"] = "0.000000"
        marker.write_text(json.dumps(started), encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "KNOWN_CHILD_PID_BIRTH_CHANGED"):
            lifecycle.verify_invocation(self.binding_path)
        self.assertTrue(output_root.is_dir())
        stop.touch()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and lifecycle.process_identity(pid) is not None:
            time.sleep(0.02)
        kqueue.close()

    def test_exit_request_without_confirmation_blocks(self):
        pid, _, kqueue, output_root, _, stop = self._start_gated_writer(detached=False)
        stop.touch()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and lifecycle.process_identity(pid) is not None:
            time.sleep(0.02)
        self.assertIsNone(lifecycle.process_identity(pid), "fixture writer did not exit")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "KNOWN_CHILD_EXIT_NOT_CONFIRMED"):
            lifecycle.verify_invocation(self.binding_path)
        self.assertTrue(output_root.is_dir())
        kqueue.close()

    def test_stale_invocation_refuses(self):
        result, record, _, _ = self._run_cli(stage="stale-check", argv=[sys.executable, "-c", "print('complete')"])
        self.assertEqual(result.returncode, 0, result.stderr)
        record_path = next((self.invocation_dir / "records").glob("*.record.json"))
        record["invocation_nonce"] = "0" * 32
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "RECORD_BINDING_MISMATCH"):
            lifecycle.verify_invocation(self.binding_path)

    def test_exit_event_precedes_each_cleanup_operation(self):
        worktree = self.source_root.parent / "cleanup-worktree"
        subprocess.run(["git", "-C", str(self.source_root), "worktree", "add", "--detach", str(worktree), "HEAD"], check=True, stdout=subprocess.DEVNULL)
        cleanup_evidence = self.root / "cleanup-evidence"
        invocation_dir, binding_path, wrapper = self._create_invocation(evidence=cleanup_evidence, worktree_root=worktree)
        lifecycle.write_wrapper(binding_path, wrapper, sys.executable)
        derived = self.root / "cleanup-DerivedData"
        harness = self.root / "cleanup-harness-bin"
        reconciliation = self.root / "cleanup-reconciliation"
        derived.mkdir()
        harness.mkdir()
        reconciliation.mkdir()
        pid, birth, kqueue, output_root, _, stop = self._start_gated_writer(detached=False, binding_path=binding_path)
        trace = self.root / "independent-cleanup-events.jsonl"

        def append(event):
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

        stop.touch()
        lifecycle._record_known_child_exit(binding_path, pid, birth, kqueue)
        append({"event": "NOTE_EXIT", "pid": pid, "birth": birth})
        operations = [
            ("worktree-remove", "git", ["git", "-C", str(self.source_root), "worktree", "remove", "--force", str(worktree)]),
            ("worktree-prune", "git", ["git", "-C", str(self.source_root), "worktree", "prune"]),
            ("DerivedData-remove", "path", [str(derived)]),
            ("harness-remove", "path", [str(harness)]),
            ("reconciliation", "path", [str(reconciliation)]),
        ]
        for label, kind, command in operations:
            self.assertEqual(lifecycle.verify_invocation(binding_path)["status"], "PASS")
            append({"event": "VERIFY_PASS", "operation": label})
            if kind == "git":
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
            else:
                shutil.rmtree(command[0])
            append({"event": "OPERATION", "operation": label})
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        exit_index = next(index for index, event in enumerate(events) if event["event"] == "NOTE_EXIT")
        for label, _, _ in operations:
            verify_index = next(index for index, event in enumerate(events) if event.get("event") == "VERIFY_PASS" and event.get("operation") == label)
            operation_index = next(index for index, event in enumerate(events) if event.get("event") == "OPERATION" and event.get("operation") == label)
            self.assertLess(exit_index, verify_index)
            self.assertLess(verify_index, operation_index)
        self.assertFalse(worktree.exists())
        self.assertFalse(derived.exists())
        self.assertFalse(harness.exists())
        self.assertFalse(reconciliation.exists())
        self.assertTrue(output_root.exists())

    def test_source_assignment_or_evidence_drift_blocks(self):
        guard_path = self.root / "assignment.json"
        guard_path.write_text(json.dumps({"task_id": "GH-420", "attempt": "fixture-a1", "state": "authenticated"}), encoding="utf-8")
        guard = {
            "path": str(guard_path),
            "sha256": lifecycle._sha256_file(guard_path),
            "task_id": "GH-420",
            "attempt": "fixture-a1",
            "authorization_identity": "synthetic-authenticated-assignment",
        }
        evidence = self.root / "guarded-evidence"
        _, guarded_binding, _ = self._create_invocation(evidence=evidence, assignment_guard=guard)
        guard_path.write_text(json.dumps({"task_id": "GH-420", "attempt": "fixture-a1", "state": "changed"}), encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "ASSIGNMENT_GUARD_CHANGED"):
            lifecycle.verify_invocation(guarded_binding)

        with self.assertRaisesRegex(lifecycle.LifecycleError, "SOURCE_NOT_CLEAN"):
            (self.source_root / "source.txt").write_text("source drift\n", encoding="utf-8")
            lifecycle.verify_invocation(self.binding_path)
        (self.source_root / "source.txt").write_text("fixture source\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.source_root), "checkout", "--", "source.txt"], check=True)

        result, record, stdout, _ = self._run_cli(stage="evidence-check", argv=[sys.executable, "-c", "print('evidence')"])
        self.assertEqual(result.returncode, 0, result.stderr)
        stdout.write_text("tampered evidence\n", encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "PROCESS_OUTPUT_HASH_MISMATCH"):
            lifecycle.verify_invocation(self.binding_path)
        self.assertTrue(stdout.exists())


if __name__ == "__main__":
    unittest.main()
