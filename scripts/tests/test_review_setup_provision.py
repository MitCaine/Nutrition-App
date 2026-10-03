"""Disposable public-route rehearsal; synthetic protocol is never qualification."""
from __future__ import annotations
import copy
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock
from test_candidate_evidence import CandidateFixture
import test_workflow_instruction_delivery as workflow_tests
from lib import candidate_evidence as evidence, independent_review as review


class ProvisionTests(CandidateFixture):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("task_provision_test", Path(__file__).resolve().parents[1]/"task.py")
        self.task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.task)
        self.controller = self.root / "controller"
        self.controller.mkdir()
        self.issue["html_url"] = "https://github.com/example/repo/issues/1"
        self.state = {"repository": "example/repo", "issue_number": 1, "task_id": "GH-1",
                      "trusted_author": "example", "phase": "AUTHORIZED"}
        self.task.atomic_write_json(self.task.state_path(self.controller, 1), self.state)
        self.ri, self.ri_commit, _, self.manifest = workflow_tests.WorkflowInstructionDeliveryTests.instructions(self)
        self.manifest_path = self.controller / "instructions.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.binary = self.root / "fixture-runtime"
        self.binary.write_text("#!" + sys.executable + "\nimport sys\nprint('codex-cli 0.159.2')\n")
        self.binary.chmod(0o700)
        self.comment = None
        self.provider = mock.Mock()
        self.provider.get_issue.return_value = self.issue
        self.provider.get_issue_comment.side_effect = lambda repo, ident: copy.deepcopy(self.comment)

    def args(self, action, *, selection=True):
        argv = ["--repo-root", str(self.repo), "--state-dir", str(self.controller),
                "evidence", "1", action, "--candidate-root", str(self.repo)]
        if action == "attach":
            argv += ["--planning", self.planning]
        if selection:
            argv += ["--runtime", str(self.binary), "--runtime-sha256", hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "--runtime-version", "codex-cli 0.159.2", "--model", "gpt-6.1-sol", "--effort", "low",
                "--workflow-repo", str(self.ri), "--workflow-commit", self.ri_commit,
                "--workflow-manifest", str(self.manifest_path),
                "--account-readiness", str(self.controller/"readiness.json"),
                "--account-route-approval", str(self.controller/"approval.json"),
                "--owner-authority-provenance", str(self.controller/"provenance.json"), "--comment-id", "123"]
        return self.task.build_parser().parse_args(argv)

    def command(self, args):
        original_git = self.task.git
        def local_git(repo, *arguments):
            return "" if arguments == ("fetch", "origin", "main") else original_git(repo, *arguments)
        with mock.patch.object(self.task, "git", side_effect=local_git), \
             mock.patch.object(self.task, "require_trusted_main_controller", return_value=self.base), \
             mock.patch.object(self.task, "repository_slug", return_value="example/repo"), \
             mock.patch.object(self.task, "resolve_current_authorization", return_value=self.auth), \
             mock.patch.object(self.task, "GhIssueAuthorizationTransport", return_value=self.provider), \
             mock.patch.object(self.task, "emit"):
            return self.task.command_evidence(args)

    def state_now(self):
        return self.task.load_state(self.controller, 1)

    def attach(self):
        self.command(self.args("attach", selection=False))
        attached = self.state_now()["capsule_evidence"]
        self.assertNotIn("review_setup_authority", attached)
        self.assertEqual((self.controller/"review-key.bin").stat().st_mode & 0o777, 0o600)
        return attached

    def readiness(self):
        self.attach()
        self.command(self.args("readiness"))
        state = self.state_now()
        expected = self.task.review_setup_owner_payload(self.args("setup"), state["capsule_evidence"],
            state["capsule_evidence"]["binding"], self.auth, self.candidate)
        self.comment = {"id": 123, "user": {"login": "example"},
            "html_url": "https://github.com/example/repo/issues/1#issuecomment-123",
            "body": self.task.REVIEW_SETUP_MARKER + "\n```json\n" + json.dumps(expected) + "\n```"}
        return state

    def protocol(self, verdict=None, unsafe=False):
        # Actual subprocess/Rpc/pipes/version/hash, but synthetic account and
        # effective-session declarations. No live service and no OS sandbox proof.
        source = r'''
import sys,json
if '--version' in sys.argv: print('codex-cli 0.159.2'); raise SystemExit
VERDICT = __VERDICT__
UNSAFE = __UNSAFE__
def send(x): print(json.dumps(x),flush=True)
for line in sys.stdin:
 m=json.loads(line); method=m.get('method'); ident=m.get('id'); p=m.get('params',{})
 if method is None:
  send({'method':'item/completed','params':{'threadId':'fixture-thread','turnId':'fixture-turn','item':{'type':'agentMessage','text':json.dumps(VERDICT)}}})
  send({'method':'turn/completed','params':{'threadId':'fixture-thread','turn':{'id':'fixture-turn','status':'completed'}}})
  continue
 if ident is None: continue
 if method=='initialize':
  if UNSAFE=='readiness-unknown': send({'method':'unexpected/unsafe','params':{}})
  result={}
 elif method=='account/read': result={'account':{'type':'chatgpt','email':'synthetic@example.invalid','planType':'prolite'},'requiresOpenaiAuth':True,'workspaceRouting':{'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT','chatgptAccountId':'synthetic-account'}}
 elif method=='model/list': result={'data':[{'model':'gpt-6.1-sol','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}],'nextCursor':None}
 elif method=='mcpServerStatus/list': result={'data':[],'nextCursor':None}
 elif method=='thread/start': result={'thread':{'id':'fixture-thread','turns':[],'ephemeral':True},'instructionSources':[],'runtimeWorkspaceRoots':[],'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False},'model':'gpt-6.1-sol','reasoningEffort':'low','modelProvider':'openai'}
 elif method=='turn/start':
  send({'id':ident,'result':{'turn':{'id':'fixture-turn'}}})
  if UNSAFE:
   send({'method':'item/completed','params':{'threadId':'fixture-thread','turnId':'fixture-turn','item':{'type':'commandExecution','command':'write outside'}}})
  else:
   send({'id':900,'method':'item/tool/call','params':{'threadId':'fixture-thread','turnId':'fixture-turn','namespace':None,'callId':'fixture-read','tool':'nutrition_read_source','arguments':{'revision':'candidate','path':'context.py','start_line':1,'end_line':1}}})
  continue
 else: raise RuntimeError(method)
 send({'id':ident,'result':result})
'''
        source = source.replace("__VERDICT__", repr(verdict)).replace("__UNSAFE__", repr(unsafe))
        self.binary.write_text("#!" + sys.executable + "\n" + source)

    def test_public_attach_readiness_setup_preflight_report_controller_consumption(self):
        # Independently fixed complete matrices, not copied from controller
        # output or generated from counts. Only exact source/binding IDs vary.
        expected = {"candidate":self.candidate,"binding_sha256":self.binding()["binding_sha256"],
            "disposition":"bounded-correction","summary":"Synthetic fixture report; no model review","findings":[],
            "matrix":[{"id":"AC-1","result":"FAIL","evidence":"Synthetic mandatory-proof rejection fixture"}],
            "outcome_review":[{"id":"OUT-1","result":"PASS","evidence":"Issue outcome maps to AC-1"}],
            "standards_review":[{"id":"STD-1","result":"PASS","evidence":"context.py:1 retains OFFSET=0"}]}
        expected_report_bytes=json.dumps(expected,indent=2).encode()
        expected_report_sha256=hashlib.sha256(expected_report_bytes).hexdigest()
        self.protocol(expected)
        before = evidence.observe(self.repo, self.candidate)
        self.readiness()
        self.command(self.args("setup"))
        state = self.state_now()
        self.assertEqual(state["capsule_evidence"]["review_setup_authority"]["launches_used"], 0)
        self.command(self.args("preflight"))
        # The external Q/state machine is a declared fixture boundary, not a
        # fabricated App qualification. Execute real immutable fixture commands.
        state = self.state_now()
        binding = state["capsule_evidence"]["binding"]
        for check in ("focused", "baseline"):
            state["capsule_evidence"]["commands"][check] = evidence.run_check(
                self.repo, binding, check, self.controller/("fixture-check-"+check))
        state["capsule_evidence"]["qualified"] = {"binding_sha256": binding["binding_sha256"], "fixture_only": True}
        state["phase"] = "VERIFIED"
        self.task.atomic_write_json(self.task.state_path(self.controller, 1), state)
        self.command(self.args("review"))
        after = self.state_now()
        self.assertEqual(after["phase"], "REVIEWED_CHANGES_REQUESTED")
        receipt = after["capsule_evidence"]["review"]
        report = json.loads(Path(receipt["report"]["path"]).read_text())
        self.assertEqual(report, expected)
        self.assertEqual(receipt["verdict"], expected)
        self.assertEqual(Path(receipt["report"]["path"]).read_bytes(),expected_report_bytes)
        self.assertEqual(receipt["report"]["sha256"],expected_report_sha256)
        self.assertEqual(receipt["report"]["sha256"], hashlib.sha256(Path(receipt["report"]["path"]).read_bytes()).hexdigest())
        self.assertEqual(receipt["session"]["workflow_instructions"]["source_commit"], self.ri_commit)
        self.assertEqual(receipt["source_before"], before)
        self.assertEqual(evidence.observe(self.repo, self.candidate), before)
        self.assertEqual(after["capsule_evidence"]["review_setup_authority"]["launches_used"], 1)
        self.assertEqual(report["standards_review"], expected["standards_review"])
        evidence.authenticate_receipt(receipt, (self.controller/"review-key.bin").read_bytes(), binding)
        output = os.environ.get("ADAPTER_PREPARATION_EVIDENCE_DIR")
        if output:
            Path(output,"fixture-roundtrip.json").write_text(json.dumps({"fixture_only":True,
                "expected_report":expected,"captured_report":report,"expected_report_sha256":expected_report_sha256,
                "report_sha256":receipt["report"]["sha256"],
                "controller_phase":after["phase"],"source_unchanged":True,"instruction_identity":receipt["session"]["workflow_instructions"],
                "actual_model_or_account_service_calls":0,"real_AppQ":False,"physical_confinement_proof":False},indent=2)+"\n")
        with self.assertRaisesRegex(evidence.EvidenceError, "PHASE_OR_ALLOWANCE"):
            self.command(self.args("setup"))

    def test_wrong_missing_changed_consumed_owner_and_readiness_reject(self):
        self.protocol()
        self.readiness()
        original = copy.deepcopy(self.comment)
        for mutate in (lambda c:c.update(id=124), lambda c:c["user"].update(login="stranger"),
                       lambda c:c.update(body=c["body"].replace('"failure_count": 0','"failure_count": 1')),
                       lambda c:c.update(html_url="https://github.com/other/repo/issues/1#issuecomment-123")):
            self.comment = copy.deepcopy(original); mutate(self.comment)
            with self.assertRaisesRegex(evidence.EvidenceError,"OWNER_COMMENT"):
                self.command(self.args("setup"))
            self.assertFalse((self.controller/"approval.json").exists())
        self.comment = original
        self.command(self.args("setup"))
        self.comment["body"] += "\nChanged after approval"
        with self.assertRaisesRegex(evidence.EvidenceError,"OWNER_COMMENT_CHANGED"):
            self.command(self.args("preflight"))
        state = self.state_now()
        state["capsule_evidence"]["pre_review_failures"] = [{}]
        self.task.atomic_write_json(self.task.state_path(self.controller,1),state)
        with self.assertRaisesRegex(evidence.EvidenceError,"PHASE_OR_ALLOWANCE"):
            self.command(self.args("setup"))

    def test_missing_existing_key_and_missing_readiness_do_not_create_authority(self):
        self.attach()
        with self.assertRaisesRegex(evidence.EvidenceError,"READINESS_STALE_OR_MISSING"):
            self.command(self.args("setup"))
        (self.controller/"review-key.bin").unlink()
        with self.assertRaisesRegex(evidence.EvidenceError,"EXISTING_ATTACHMENT_KEY"):
            self.command(self.args("readiness"))
        self.assertFalse((self.controller/"review-key.bin").exists())

    def test_source_change_stopped_phase_and_wrong_exact_selection_block(self):
        self.attach()
        args = self.args("readiness"); args.model="gpt-5.6-sol"
        with self.assertRaisesRegex(evidence.EvidenceError,"EXACT_SELECTION"):
            self.command(args)
        state=self.state_now(); state["phase"]="STOP_REPLAN"
        self.task.atomic_write_json(self.task.state_path(self.controller,1),state)
        with self.assertRaisesRegex(evidence.EvidenceError,"PHASE_OR_ALLOWANCE"):
            self.command(self.args("readiness"))
        state["phase"]="AUTHORIZED"; self.task.atomic_write_json(self.task.state_path(self.controller,1),state)
        (self.repo/"app.py").write_text("changed source\n")
        with self.assertRaisesRegex(evidence.EvidenceError,"CANDIDATE_NOT_CLEAN|ATTACHED_SOURCE_CHANGED"):
            self.command(self.args("readiness"))

    def test_source_callbacks_are_committed_bounded_and_cannot_address_outside(self):
        binding=self.binding(); original=(self.repo/"context.py").read_text()
        (self.repo/"context.py").write_text("untrusted working bytes\n")
        result=review.read_source(self.repo,binding,"nutrition_read_source",
            {"revision":"candidate","path":"context.py","start_line":1,"end_line":1})
        self.assertIn(original.strip(),result["content"])
        for path in ("../outside", ".git/config", "/private/tmp/outside"):
            with self.assertRaises(evidence.EvidenceError):
                review.read_source(self.repo,binding,"nutrition_read_source",
                    {"revision":"candidate","path":path,"start_line":1,"end_line":1})
        with self.assertRaises(evidence.EvidenceError):
            review.read_source(self.repo,binding,"nutrition_read_source",
                {"revision":"candidate","path":"context.py","start_line":1,"end_line":500})

    def test_actual_nested_command_sandbox_denies_source_git_and_outside_writes(self):
        outside=self.root/"outside-sentinel"; outside.write_text("unchanged\n")
        code = "\n".join([
            "from pathlib import Path", "import sys",
            "root=Path(sys.argv[1]); outside=Path(sys.argv[2])",
            "for path in [root/'app.py',root/'.git/config',outside]:",
            " try: path.open('r+b').close()",
            " except PermissionError: pass",
            " else: raise AssertionError('unexpected write permission: '+str(path))",
        ])
        requirements=copy.deepcopy(self.requirements)
        requirements[0]["argv"]=["{python}","-c",code,"{repository}",str(outside)]
        original=self.original.replace(json.dumps(self.requirements),json.dumps(requirements))
        self.git("reset","--hard",self.base)
        self.capsule.parent.mkdir(parents=True,exist_ok=True); self.capsule.write_text(original)
        self.git("add","."); self.git("commit","-qm","protected negative fixture planning")
        self.planning=self.git("rev-parse","HEAD")
        self.capsule.write_text(original.replace('state = "READY"','state = "IMPLEMENTED"'))
        (self.repo/"app.py").write_text("def add(a,b):\n    return a+b\n")
        self.git("add","."); self.git("commit","-qm","protected negative fixture candidate")
        self.candidate=self.git("rev-parse","HEAD")
        binding=self.binding(); before=evidence.observe(self.repo,self.candidate)
        result=evidence.run_check(self.repo,binding,"focused",self.controller/"confinement-command")
        self.assertEqual(result["status"],"passed",result)
        self.assertEqual(outside.read_text(),"unchanged\n")
        self.assertEqual(evidence.observe(self.repo,self.candidate),before)
        output=os.environ.get("ADAPTER_PREPARATION_EVIDENCE_DIR")
        if output:
            Path(output,"fixture-nested-confinement.json").write_text(json.dumps({"fixture_only":True,
                "actual_helper":"candidate_evidence.run_check","actual_nested_launcher":"/usr/bin/sandbox-exec",
                "source_git_outside_write_denials":3,"status":result["status"],"exit_code":result["exit_code"],
                "source_unchanged":True,"outside_unchanged":True,"sandbox_sha256":result["artifacts"]["sandbox.sb"]["sha256"],
                "runtime":result["runtime"],"protected_model_reviewer_qualified":False},indent=2)+"\n")

    def test_readiness_changes_unknown_trace_and_report_completeness_reject(self):
        self.protocol()
        with mock.patch.object(review,"Rpc") as rpc_factory:
            rpc=rpc_factory.return_value; rpc.trace=[]
            rpc.request.return_value={}
            witness={"authMode":"chatgpt","planType":"prolite","route":{"backendOrigin":"https://chatgpt.com","accountRoutingOverride":"NO_CONSTRAINT"},"identity_hmac_sha256":"a"*64,"requiresOpenaiAuth":True,"redacted":True}
            with mock.patch.object(review,"read_account_witness",side_effect=[(witness,2),({**witness,"identity_hmac_sha256":"b"*64},3)]), \
                 mock.patch.object(review.subprocess,"Popen"), \
                 mock.patch.object(review,"runtime",return_value={"version":"codex-cli 0.159.2","executable":str(self.binary)}):
                with self.assertRaisesRegex(evidence.EvidenceError,"ACCOUNT_CHANGED"):
                    review.account_readiness(self.binary,hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                        directory=self.controller/"changed",key=b"k"*32,route=witness["route"])
        binding=self.binding(); invalid=self.verdict(binding)
        invalid["standards_review"]=[]
        with self.assertRaisesRegex(evidence.EvidenceError,"OBLIGATION_MATRIX_INCOMPLETE"):
            evidence.validate_verdict(binding,invalid)
        invalid=self.verdict(binding); invalid["matrix"]=[]
        with self.assertRaisesRegex(evidence.EvidenceError,"ACCEPTANCE_MATRIX_INCOMPLETE"):
            evidence.validate_verdict(binding,invalid)
        reader=review.Rpc.__new__(review.Rpc)
        reader.buffer=b"x"*8_000_001; reader.received_bytes=0; reader.deadline=time.monotonic()+5
        reader.selector=mock.Mock(); reader.selector.select.return_value=True; reader.process=mock.Mock()
        with mock.patch.object(review.os,"read",return_value=b"x"):
            with self.assertRaisesRegex(evidence.EvidenceError,"TRACE_LIMIT"):
                reader.read()
        reader.buffer=b""; reader.received_bytes=32_000_000
        with mock.patch.object(review.os,"read",return_value=b"x"):
            with self.assertRaisesRegex(evidence.EvidenceError,"TRACE_LIMIT"):
                reader.read()

    def test_correction_discards_setup_and_preserves_consumed_history(self):
        self.protocol()
        self.readiness(); self.command(self.args("setup"))
        state=self.state_now(); attached=state["capsule_evidence"]
        attached["review_setup_authority"]["launches_used"]=1
        attached["review"]={"verdict":{"disposition":"bounded-correction"}}
        state["phase"]="REVIEWED_CHANGES_REQUESTED"
        corrected=evidence.correction(state)
        self.assertNotIn("review_setup_authority",corrected["capsule_evidence"])
        self.assertNotIn("review_readiness",corrected["capsule_evidence"])
        self.assertEqual(corrected["evidence_history"][-1]["review_setup_authority"]["launches_used"],1)

    def test_actual_readiness_unknown_event_is_sticky_stop_and_cannot_provision(self):
        self.protocol(unsafe="readiness-unknown")
        self.attach()
        with self.assertRaisesRegex(evidence.EvidenceError,"READINESS_TRACE_UNSAFE"):
            self.command(self.args("readiness"))
        stopped=self.state_now()
        self.assertEqual(stopped["phase"],"STOP_REPLAN")
        self.assertNotIn("review_setup_authority",stopped["capsule_evidence"])
        self.assertFalse((self.controller/"readiness.json").exists())
        with self.assertRaisesRegex(evidence.EvidenceError,"PHASE_OR_ALLOWANCE"):
            self.command(self.args("setup"))
        self.assertEqual(self.state_now(),stopped)
