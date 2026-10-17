from __future__ import annotations

import json
import os
import plistlib
import shutil
import shlex
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


class UnwrappedToolInventoryTests(unittest.TestCase):
    def test_actual_xcodebuild_ibc_exec_forms_are_settings_not_processes(self):
        wrapper = "/private/tmp/gh421-minimal-positive-be748c91/native-lifecycle/ibtool"
        selected_ibtool = "/Applications/Xcode.app/Contents/Developer/usr/bin/ibtool"
        actual_invocation = (
            "    /Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project "
            "/private/tmp/gh421-minimal-positive-be748c91/worktree/apps/mobile/ios/Probe.xcodeproj "
            "-scheme Probe -configuration Debug -sdk iphonesimulator -destination "
            '"generic/platform=iOS Simulator" -derivedDataPath '
            "/private/tmp/gh421-minimal-positive-be748c91/DerivedData CODE_SIGNING_ALLOWED=NO "
            f"IBC_EXEC={wrapper} build"
        )
        displayed_settings = [
            "Build settings from command line:",
            "    CODE_SIGNING_ALLOWED = NO",
            f"    IBC_EXEC = {wrapper}",
            "    SDKROOT = iphonesimulator27.1",
        ]

        direct, version = lifecycle._unwrapped_tool_lines(
            [actual_invocation, *displayed_settings], wrapper, selected_ibtool
        )

        self.assertEqual(direct, [])
        self.assertEqual(version, [])

    def test_direct_vendor_calls_and_wrong_executable_remain_visible(self):
        wrapper = "/private/tmp/native-lifecycle/ibtool"
        selected_ibtool = "/Applications/Xcode.app/Contents/Developer/usr/bin/ibtool"
        wrong_ibtool = "/tmp/unselected-xcode/usr/bin/ibtool"
        direct_vendor_call = f"ExecuteExternalTool {selected_ibtool} --compile input.storyboard"
        wrong_version_call = f"ExecuteExternalTool {wrong_ibtool} --version --output-format xml1"
        setting_beside_direct_call = f"IBC_EXEC={wrapper} {selected_ibtool} --compile input.storyboard"
        selected_version_call = f"ExecuteExternalTool {selected_ibtool} --version --output-format xml1"
        wrapper_version_call = f"ExecuteExternalTool {wrapper} --version --output-format xml1"

        direct, version = lifecycle._unwrapped_tool_lines(
            [
                direct_vendor_call,
                wrong_version_call,
                setting_beside_direct_call,
                selected_version_call,
                wrapper_version_call,
            ],
            wrapper,
            selected_ibtool,
        )

        self.assertEqual(direct, [direct_vendor_call, wrong_version_call, setting_beside_direct_call])
        self.assertEqual(version, [selected_version_call])


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
        self.ibtoold = Path("/bin/bash")
        self.ibtool.write_text(
            "#!/bin/bash\n"
            "sleep \"${NATIVE_TEST_IBTOOL_SLEEP:-0.25}\"\n"
            "if [ -n \"${NATIVE_TEST_CALLS:-}\" ]; then printf '%s\\n' \"$*\" >> \"$NATIVE_TEST_CALLS\"; fi\n"
            "if [ -n \"${NATIVE_TEST_ENVIRONMENT:-}\" ]; then\n"
            "  secret=null\n"
            "  if env | grep -q '^IBTOOLD-SECRET='; then secret='\\\"present\\\"'; fi\n"
            "  printf '{\"IBToolNeverDeque\":\"%s\",\"IBTOOLD-SECRET\":%s}\\n' \"${IBToolNeverDeque:-}\" \"$secret\" > \"$NATIVE_TEST_ENVIRONMENT\"\n"
            "fi\n"
            "if [ \"${1-}\" = --version ] && [ \"${2-}\" = --output-format ] && [ \"${3-}\" = xml1 ]; then\n"
            "  printf '%s\\n' '<?xml version=\"1.0\" encoding=\"UTF-8\"?>' '<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">' '<plist version=\"1.0\"><dict><key>com.apple.ibtool.version</key><string>27.1</string></dict></plist>'\n"
            "  exit 0\n"
            "fi\n"
            "operation=\noutput=\nsource=\ncompilation_directory=\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  arg=$1; shift\n"
            "  case \"$arg\" in\n"
            "    --compile) operation=compile; output=$1; source=$2; shift 2 ;;\n"
            "    --compilation-directory) operation=compile; compilation_directory=$1; shift ;;\n"
            "    --link) operation=link; output=$1; source=$2; shift 2 ;;\n"
            "    *.storyboard|*.storyboardc) source=$arg ;;\n"
            "  esac\n"
            "done\n"
            "if [ \"$operation\" = compile ] && [ \"${NATIVE_TEST_FAIL_COMPILE:-0}\" = 1 ]; then exit 17; fi\n"
            "if [ \"$operation\" = compile ]; then\n"
            "  if [ -n \"$compilation_directory\" ]; then\n"
            "    base=${source##*/}; base=${base%.storyboard}; output=$compilation_directory/$base.storyboardc\n"
            "  fi\n"
            "  mkdir -p \"$output\"\n"
            "  printf 'compiled storyboard\\n' > \"$output/compiled.txt\"\n"
            "elif [ \"$operation\" = link ]; then\n"
            "  mkdir -p \"$output\"\n"
            "  destination=\"$output/${source##*/}\"\n"
            "  rm -rf \"$destination\"\n"
            "  cp -R \"$source\" \"$destination\"\n"
            "fi\n"
            "printf 'vendor stdout\\000\\n'\n"
            "printf 'vendor stderr\\377\\n' >&2\n",
            encoding="utf-8",
        )
        self.ibtool.chmod(0o700)
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
        ibtool_path: Path | None = None,
        ibtoold_path: Path | None = None,
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
            ibtool_path=ibtool_path or self.ibtool,
            ibtoold_path=ibtoold_path or self.ibtoold,
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

    def _run_wrapper(
        self,
        argv: list[str],
        *,
        environment: dict[str, str] | None = None,
        wrapper_path: Path | None = None,
    ):
        env = os.environ.copy()
        env.update(NATIVE_TEST_CALLS=str(self.calls_file), NATIVE_TEST_ENVIRONMENT=str(self.environment_file))
        if environment:
            env.update(environment)
        return subprocess.run(
            [str(wrapper_path or self.wrapper_path), *argv],
            cwd=self.source_root,
            env=env,
            capture_output=True,
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
        self.assertEqual(result.stdout, b"vendor stdout\x00\n")
        self.assertEqual(result.stderr, b"vendor stderr\xff\n")
        records = sorted((self.invocation_dir / "records").glob("*.record.json"))
        record = json.loads(records[-1].read_text(encoding="utf-8"))
        self.assertEqual(record["stage"], "version")
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["child_exit"], 0)
        self.assertEqual(record["exec_transition"]["executable"], str(self.ibtoold))
        self.assertEqual(record["process"]["pid"], record["exec_transition"]["pid"])
        self.assertEqual(record["process"]["birth"], record["exec_transition"]["birth"])
        self.assertEqual(record["environment_allowlist"]["IBToolNeverDeque"], "1")
        self.assertNotIn("IBTOOLD-SECRET", record["environment_allowlist"])
        self.assertEqual(Path(record["stdout"]["path"]).read_bytes(), result.stdout)
        self.assertEqual(Path(record["stderr"]["path"]).read_bytes(), result.stderr)
        observed = json.loads(self.environment_file.read_text(encoding="utf-8"))
        self.assertEqual(observed, {"IBToolNeverDeque": "1", "IBTOOLD-SECRET": None})

    def test_wrapper_preserves_basename_derived_vendor_version_xml(self):
        result = self._run_wrapper(["--version", "--output-format", "xml1"])
        self.assertEqual(result.returncode, 0, result.stderr)
        version = plistlib.loads(result.stdout)
        expected_key = f"com.apple.{self.wrapper_path.name}.version"
        self.assertEqual(version, {expected_key: "27.1"})
        record = json.loads(
            sorted((self.invocation_dir / "records").glob("*.record.json"))[-1].read_text(encoding="utf-8")
        )
        self.assertEqual(Path(record["stdout"]["path"]).read_bytes(), result.stdout)

    def test_child_exit_remains_distinct_when_note_exit_observation_fails(self):
        binding, _ = lifecycle._binding(self.binding_path)
        environment = os.environ.copy()
        environment.update(NATIVE_TEST_CALLS=str(self.calls_file), NATIVE_TEST_ENVIRONMENT=str(self.environment_file))
        with patch.object(lifecycle, "_wait_note_exit", return_value=False):
            status, record = lifecycle._run_gated_ibtool(
                self.binding_path,
                binding,
                [str(self.ibtool), "--version"],
                stage="version",
                environment=environment,
                timeout=5,
            )
        self.assertEqual(status, 1)
        self.assertEqual(Path(record["stdout"]["path"]).read_bytes(), b"vendor stdout\x00\n")
        self.assertEqual(Path(record["stderr"]["path"]).read_bytes(), b"vendor stderr\xff\n")
        self.assertEqual(record["child_exit"], 0)
        self.assertEqual(record["observation_error"], "CHILD_NOTE_EXIT_UNOBSERVED")
        self.assertEqual(record["status"], "FAILURE")

    def test_gated_ibtool_transition_and_execution_share_one_deadline(self):
        delayed_ibtool = self.tools / "delayed-ibtool"
        delayed_source = self.tools / "delayed-ibtool.c"
        delayed_source.write_text(
            "#include <unistd.h>\n"
            "int main(int argc, char **argv) {\n"
            "  (void)argc; (void)argv;\n"
            "  usleep(300000);\n"
            "  execl(\"/bin/sleep\", \"/bin/sleep\", \"0.6\", (char *)0);\n"
            "  return 127;\n"
            "}\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["/usr/bin/clang", "-Wall", "-Wextra", "-Werror", str(delayed_source), "-o", str(delayed_ibtool)],
            check=True,
            capture_output=True,
            text=True,
        )
        _, binding_path, wrapper_path = self._create_invocation(
            evidence=self.evidence / "delayed-transition",
            ibtool_path=delayed_ibtool,
            ibtoold_path=Path("/bin/sleep"),
        )
        lifecycle.write_wrapper(binding_path, wrapper_path, sys.executable)
        binding, _ = lifecycle._binding(binding_path)

        status, record = lifecycle._run_gated_ibtool(
            binding_path,
            binding,
            [str(delayed_ibtool), "--version"],
            stage="version",
            environment=os.environ.copy(),
            timeout=0.8,
        )

        self.assertEqual(status, 1)
        self.assertTrue(record["timed_out"], record)
        self.assertIsNone(record["child_exit"])
        self.assertIsNotNone(record["exec_transition"], record)
        self.assertEqual(
            record["exec_transition"]["executable"],
            binding["toolchain"]["tools"]["ibtoold"]["path"],
        )
        self.assertIsNone(record["observation_error"])
        child_pid = record["process"]["pid"]
        deadline = time.monotonic() + 3
        while lifecycle.process_identity(child_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIsNone(lifecycle.process_identity(child_pid), "delayed fake ibtool did not exit naturally")

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

    def _prepare_full_build_fixture(
        self,
        *,
        prebuild_compile: bool = False,
        include_wrapper_commands: bool = True,
        unmatched_link_command: bool = False,
        alias_paths: bool = False,
        wrong_wrapper_executable: bool = False,
        legacy_compile: bool = False,
        logged_compilation_directory: Path | None = None,
        task_storyboard_override: Path | None = None,
        mutate_compile_record: bool = False,
        remove_compile_output: bool = False,
        omit_compile_wrapper_command: bool = False,
    ):
        lifecycle.record_phase(self.binding_path, "capability-required")
        storyboard = self.root / "generated" / "SplashScreen.storyboard"
        storyboard.parent.mkdir()
        storyboard.write_text("<document type='com.apple.InterfaceBuilder3.CocoaTouch.Storyboard.XIB'/>\n", encoding="utf-8")
        code, cap_record = lifecycle.run_capability(
            self.binding_path,
            storyboard,
            self.invocation_dir / "capability",
        )
        self.assertEqual(code, 0, cap_record)
        compile_output = self.root / "DerivedData" / "Build" / "Intermediates" / "SplashScreen.storyboardc"
        compile_output.parent.mkdir(parents=True)
        app_product = self.root / "DerivedData" / "Build" / "Products" / "NutritionApp.app"
        if alias_paths:
            alias_root = self.root / "Nutrition App Native alias"
            alias_root.symlink_to(self.root, target_is_directory=True)

            def fixture_path(path: Path) -> Path:
                return alias_root / path.relative_to(self.root)

        else:

            def fixture_path(path: Path) -> Path:
                return path

        command_wrapper = fixture_path(self.wrapper_path)
        if wrong_wrapper_executable:
            wrong_wrapper = self.root / "wrong executable with spaces" / "ibtool"
            wrong_wrapper.parent.mkdir(parents=True)
            wrong_wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            command_wrapper = wrong_wrapper
        storyboard_arg = fixture_path(storyboard)
        compile_output_arg = fixture_path(compile_output)
        compilation_directory_arg = fixture_path(compile_output.parent)
        if legacy_compile:
            compile_args = [
                "--errors", "--warnings", "--notices", "--output-format", "human-readable-text",
                "--compile", str(compile_output_arg), str(storyboard_arg),
            ]
        else:
            compile_args = [
                "--errors", "--warnings", "--notices", "--output-format", "human-readable-text",
                str(storyboard_arg), "--compilation-directory", str(compilation_directory_arg),
            ]
        link_args = [
            "--errors", "--warnings", "--notices", "--output-format", "human-readable-text",
            "--link", str(fixture_path(app_product)), str(compile_output_arg),
        ]
        if prebuild_compile:
            compiled = self._run_wrapper(compile_args, wrapper_path=fixture_path(self.wrapper_path))
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
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
        lifecycle.record_phase(
            self.binding_path,
            "xcode-build-started",
            build_invocation=str(build_invocation),
        )
        if not prebuild_compile:
            compiled = self._run_wrapper(compile_args, wrapper_path=fixture_path(self.wrapper_path))
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
        linked = self._run_wrapper(link_args, wrapper_path=fixture_path(self.wrapper_path))
        self.assertEqual(linked.returncode, 0, linked.stderr)
        if mutate_compile_record:
            for record_path in sorted((self.invocation_dir / "records").glob("*.record.json")):
                document = json.loads(record_path.read_text(encoding="utf-8"))
                if document.get("stage") == "compile":
                    document["argv"][-1] = str(self.root / "different-record-source.storyboard")
                    record_path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
                    break
            else:
                self.fail("compile record was not written")
        if remove_compile_output:
            shutil.rmtree(compile_output)
        lifecycle.record_phase(
            self.binding_path,
            "xcode-build-finished",
            build_invocation=str(build_invocation),
            xcodebuild_exit=0,
        )
        logged_compile_args = list(compile_args)
        if logged_compilation_directory is not None and not legacy_compile:
            logged_compile_args[logged_compile_args.index("--compilation-directory") + 1] = str(
                fixture_path(logged_compilation_directory)
            )
        logged_link_args = list(link_args)
        if unmatched_link_command:
            logged_link_args[logged_link_args.index("--link") + 2] = str(self.root / "unmatched-link.storyboardc")
        def xcode_escape(value: str | Path) -> str:
            return str(value).replace("\\", "\\\\").replace(" ", "\\ ")

        def xcode_command_line(argv: list[str]) -> str:
            return " ".join(xcode_escape(value) for value in argv)

        command_lines = []
        if include_wrapper_commands:
            if not omit_compile_wrapper_command:
                command_lines.append(xcode_command_line([str(command_wrapper), *logged_compile_args]))
            command_lines.append(xcode_command_line([str(command_wrapper), *logged_link_args]))
        task_storyboard = task_storyboard_override or storyboard_arg
        build_log = self.evidence / "xcodebuild.log"
        build_log.write_text(
            "Command line invocation:\n"
            f"{shlex.join([str(Path(sys.executable).resolve()), '-project', str(self.root / 'Probe.xcodeproj'), f'IBC_EXEC={self.wrapper_path}', 'build'])}\n"
            "\n"
            "Build settings from command line:\n"
            f"    IBC_EXEC = {self.wrapper_path}\n"
            f"CompileStoryboard {xcode_escape(task_storyboard)} (in target 'NutritionApp')\n"
            "LinkStoryboards (in target 'NutritionApp')\n"
            + "\n".join(command_lines)
            + ("\n" if command_lines else ""),
            encoding="utf-8",
        )
        return build_invocation, build_log, app_product

    def test_fullbuild_propagation_requires_compile_and_link_records(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture()
        lifecycle.write_full_build_proof(
            self.binding_path,
            build_invocation_path=build_invocation,
            build_log_path=build_log,
            app_product_path=app_product,
        )
        self.assertEqual(lifecycle.verify_invocation(self.binding_path)["status"], "PASS")
        proof = json.loads((self.invocation_dir / "full-build-proof.json").read_text(encoding="utf-8"))
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["xcode_tasks"]["compile_count"], 1)
        self.assertEqual(proof["xcode_tasks"]["link_count"], 1)
        self.assertEqual(len(proof["wrapper_commands"]), 2)
        self.assertEqual(proof["storyboard_compile_outputs"][0]["source"], str(self.root / "generated" / "SplashScreen.storyboard"))
        self.assertEqual(
            proof["storyboard_compile_outputs"][0]["output"],
            str(self.root / "DerivedData" / "Build" / "Intermediates" / "SplashScreen.storyboardc"),
        )
        self.assertGreater(proof["build_interval"]["finished_monotonic_ns"], proof["build_interval"]["started_monotonic_ns"])

    def test_fullbuild_legacy_compile_form_remains_supported(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(legacy_compile=True)
        lifecycle.write_full_build_proof(
            self.binding_path,
            build_invocation_path=build_invocation,
            build_log_path=build_log,
            app_product_path=app_product,
        )
        proof = json.loads((self.invocation_dir / "full-build-proof.json").read_text(encoding="utf-8"))
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(
            proof["storyboard_compile_outputs"][0]["output"],
            str(self.root / "DerivedData" / "Build" / "Intermediates" / "SplashScreen.storyboardc"),
        )

    def test_fullbuild_correlates_spaces_and_filesystem_aliases(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(alias_paths=True)
        lifecycle.write_full_build_proof(
            self.binding_path,
            build_invocation_path=build_invocation,
            build_log_path=build_log,
            app_product_path=app_product,
        )
        proof = json.loads((self.invocation_dir / "full-build-proof.json").read_text(encoding="utf-8"))
        self.assertEqual(proof["status"], "PASS")
        self.assertTrue(all(r"Nutrition\ App\ Native\ alias" in item["line"] for item in proof["wrapper_commands"]))
        task_heading = next(line for line in build_log.read_text(encoding="utf-8").splitlines() if line.startswith("CompileStoryboard"))
        self.assertIn(r"Nutrition\ App\ Native\ alias", task_heading)
        alias_wrapper = str(self.root / "Nutrition App Native alias" / "evidence" / "native-lifecycle" / "ibtool")
        records = lifecycle._completed_records(self.invocation_dir)
        wrapper_records = [record for record in records if record.get("stage") in {"compile", "link"}]
        aliased_records = [{**record, "wrapper": alias_wrapper} for record in wrapper_records]
        commands = lifecycle._correlate_wrapper_commands(
            build_log.read_text(encoding="utf-8").splitlines(),
            str(self.wrapper_path),
            aliased_records,
        )
        self.assertEqual(len(commands), 2)

    def test_fullbuild_rejects_prebuild_compile_record(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(prebuild_compile=True)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_IB_RECORD_OUTSIDE_BUILD_INTERVAL"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_unmatched_link_command(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(unmatched_link_command=True)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_WRAPPER_COMMAND_RECORD_UNMATCHED"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_missing_logged_wrapper_command(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(include_wrapper_commands=False)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_WRAPPER_COMMAND_RECORD_COUNT_MISMATCH"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_missing_compile_wrapper_command(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(
            omit_compile_wrapper_command=True,
        )
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_WRAPPER_COMMAND_RECORD_COUNT_MISMATCH"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_compilation_directory_mismatch(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(
            logged_compilation_directory=self.root / "different compilation directory",
        )
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_WRAPPER_COMMAND_RECORD_UNMATCHED"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_task_source_mismatch(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(
            task_storyboard_override=self.root / "different-task-source.storyboard",
        )
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_IB_RECORD_COUNT_MISMATCH"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_record_source_mismatch(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(
            mutate_compile_record=True,
        )
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_WRAPPER_COMMAND_RECORD_UNMATCHED"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_missing_generated_compile_output(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(
            remove_compile_output=True,
        )
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_STORYBOARD_COMPILE_OUTPUT_MISSING"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

    def test_fullbuild_rejects_different_executable_with_same_basename(self):
        build_invocation, build_log, app_product = self._prepare_full_build_fixture(
            wrong_wrapper_executable=True,
        )
        with self.assertRaisesRegex(lifecycle.LifecycleError, "BUILD_WRAPPER_COMMAND_RECORD_COUNT_MISMATCH"):
            lifecycle.write_full_build_proof(
                self.binding_path,
                build_invocation_path=build_invocation,
                build_log_path=build_log,
                app_product_path=app_product,
            )

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
