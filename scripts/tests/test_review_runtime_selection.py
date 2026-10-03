from __future__ import annotations
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import independent_review as review
from lib import candidate_evidence as evidence
from test_candidate_evidence import CandidateFixture

class RuntimeSelectionTests(CandidateFixture):
    def test_exact_supported_version_and_binary_digest_without_auto_upgrade(self):
        binary=Path(sys.executable).resolve()
        sha=hashlib.sha256(binary.read_bytes()).hexdigest()
        for selected in review.SUPPORTED_ADAPTER_VERSIONS:
            with mock.patch.object(review.subprocess, 'run', return_value=mock.Mock(stdout=selected)):
                identity=review.runtime(binary,sha,selected)
                self.assertEqual(identity['version'],selected)
                self.assertEqual(identity['executable'],str(binary))
                self.assertEqual(identity['sha256'],sha)
        with mock.patch.object(review.subprocess,'run',return_value=mock.Mock(stdout='codex-cli 0.159.2')):
            with self.assertRaisesRegex(evidence.EvidenceError,'VERSION_UNQUALIFIED'):
                review.runtime(binary,sha) # Legacy caller never implicitly selects new runtime.
        with self.assertRaisesRegex(evidence.EvidenceError,'VERSION_UNQUALIFIED'):
            review.runtime(binary,sha,'codex-cli 99.9.9')
        with self.assertRaisesRegex(evidence.EvidenceError,'BYTES_CHANGED'):
            review.runtime(binary,'0'*64,'codex-cli 0.159.2')

    def task(self):
        spec=importlib.util.spec_from_file_location('task_runtime_test',Path(__file__).resolve().parents[1]/'task.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_candidate_epoch_path_digest_version_model_and_effort_are_bound(self):
        task=self.task();binding=self.binding();binary=Path(sys.executable).resolve(); sha='a'*64
        preflight={'binding_sha256':binding['binding_sha256'],'candidate_sha':self.candidate,'failure_count':0,
                   'model':'gpt-6.1-sol','effort':'low','runtime':{'executable':str(binary),'sha256':sha,'version':'codex-cli 0.159.2'}}
        attached={'review_preflight':preflight}
        kwargs=dict(runtime=binary,runtime_sha256=sha,model='gpt-6.1-sol',effort='low',runtime_version='codex-cli 0.159.2')
        self.assertEqual(task.require_review_preflight(attached,binding,self.candidate,**kwargs),preflight)
        for field,value in [('runtime',self.root/'wrong'),('runtime_sha256','b'*64),('runtime_version',review.QUALIFIED_VERSION),('model','substitute'),('effort','high')]:
            with self.assertRaisesRegex(evidence.EvidenceError,'SELECTION_NOT_PREFLIGHTED'):
                task.require_review_preflight(attached,binding,self.candidate,**{**kwargs,field:value})
        for field,value in [('candidate_sha',self.planning),('binding_sha256','0'*64),('failure_count',1)]:
            bad=copy.deepcopy(preflight);bad[field]=value
            with self.assertRaisesRegex(evidence.EvidenceError,'REQUIRED_OR_STALE'):
                task.require_review_preflight({'review_preflight':bad},binding,self.candidate,**kwargs)
        legacy=copy.deepcopy(preflight);legacy['runtime'].pop('version')
        task.require_review_preflight({'review_preflight':legacy},binding,self.candidate,**{**kwargs,'runtime_version':review.QUALIFIED_VERSION})

    def test_preflight_rejects_exact_missing_model_or_effort_without_launching_thread(self):
        binary=Path(sys.executable).resolve();identity={'executable':str(binary),'sha256':'fixture','version':'codex-cli 0.159.2'}
        for model,effort,error in [('missing','low','MODEL_UNSUPPORTED'),('gpt-6.1-sol','high','EFFORT_UNSUPPORTED')]:
            rpc=mock.Mock();rpc.trace=[];rpc.request.side_effect=[{}, {'data':[{'model':'gpt-6.1-sol','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}]
            with mock.patch.object(review,'runtime',return_value=identity),mock.patch.object(review.subprocess,'Popen'),mock.patch.object(review,'Rpc',return_value=rpc):
                with self.assertRaisesRegex(evidence.EvidenceError,error):
                    review.preflight_model(binary,'fixture',model,effort,directory=self.root/model,expected_runtime_version='codex-cli 0.159.2')
            self.assertEqual([c.args[0] for c in rpc.request.call_args_list],['initialize','model/list'])
            rpc.close.assert_called_once()

    def test_run_review_rejects_identity_replay_before_process_launch(self):
        binding=self.binding();binary=Path(sys.executable).resolve()
        identity={'executable':str(binary),'sha256':'fixture','version':'codex-cli 0.159.2','transport':'codex-app-server-environment-free-v1'}
        for field,value in [('version',review.QUALIFIED_VERSION),('executable',str(self.root/'other')),('sha256','stale')]:
            with mock.patch.object(review,'runtime',return_value=identity),mock.patch.object(review.subprocess,'Popen') as process:
                with self.assertRaisesRegex(evidence.EvidenceError,'SELECTION_CHANGED'):
                    review.run_review(self.repo,binding,{},directory=self.root/'never-start',executable=binary,expected_sha256='fixture',key=b'k'*32,
                        expected_runtime_version='codex-cli 0.159.2',expected_runtime_identity={**identity,field:value})
                process.assert_not_called()
