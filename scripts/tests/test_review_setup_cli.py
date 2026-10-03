"""Portable synthetic setup and public CLI integration; no live runtime/model."""
import copy,hashlib,importlib.util,json,sys,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib import independent_review as review,candidate_evidence as evidence
from test_candidate_evidence import CandidateFixture
import test_workflow_instruction_delivery as workflow_tests

class ReviewSetupCliTests(CandidateFixture):
 def setup(self,action='preflight'):
  spec=importlib.util.spec_from_file_location('task_setup_test',Path(__file__).resolve().parents[1]/'task.py');task=importlib.util.module_from_spec(spec);spec.loader.exec_module(task)
  repo,commit,bundle,manifest=workflow_tests.WorkflowInstructionDeliveryTests.instructions(self)
  state_dir=self.root/'controller';state_dir.mkdir()
  runtime={'executable':str(Path(sys.executable).resolve()),'sha256':'a'*64,'version':'codex-cli 0.159.2','transport':'codex-app-server-environment-free-v1'}
  route={'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'}
  witness=review.account_witness({'account':{'type':'chatgpt','email':'fixture@example.invalid','planType':'prolite'},'requiresOpenaiAuth':True,'workspaceRouting':{**route,'chatgptAccountId':'fixture-account'}},b'k'*32,route)
  paths={n:self.root/(n+'.json') for n in ('manifest','readiness','approval','provenance')}
  def save(n,value):paths[n].write_text(json.dumps(value,indent=2)+'\n')
  sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
  save('manifest',manifest);save('readiness',{'phase':'routeObservedNotApproved','runtime':runtime,'witness':witness})
  approval={'attempt':'synthetic-unconsumed','destination':'OpenAI Codex app-server','model':'gpt-6.1-sol','effort':'low','launch_limit':1,'retries':0,'route':route,'readiness_sha256':sha(paths['readiness']),'runtime':runtime,'account_identity_hmac_sha256':witness['identity_hmac_sha256']};save('approval',approval)
  save('provenance',{'source_thread':'synthetic-controller','human_turn':'synthetic-human-decision','approval_sha256':sha(paths['approval'])})
  args=task.build_parser().parse_args(['--repo-root',str(self.repo),'--state-dir',str(state_dir),'evidence','1',action,'--candidate-root',str(self.repo),'--runtime',runtime['executable'],'--runtime-sha256',runtime['sha256'],'--runtime-version',runtime['version'],'--model','gpt-6.1-sol','--effort','low','--workflow-repo',str(repo),'--workflow-commit',commit,'--workflow-manifest',str(paths['manifest']),'--account-route-approval',str(paths['approval']),'--account-readiness',str(paths['readiness']),'--owner-authority-provenance',str(paths['provenance'])])
  binding=self.binding();instruction_identity,_=review.authenticate_workflow_instructions(bundle,commit,manifest)
  identity={'binding_sha256':binding['binding_sha256'],'candidate_sha':self.candidate,'failure_count':0,'workflow_repo':str(repo.resolve()),'workflow_commit':commit,'workflow_manifest_sha256':sha(paths['manifest']),'workflow_instructions':instruction_identity,'approval_sha256':sha(paths['approval']),'readiness_sha256':sha(paths['readiness']),'provenance_sha256':sha(paths['provenance']),'attempt':approval['attempt'],'runtime':runtime,'model':args.model,'effort':args.effort,'route':route,'account_identity_hmac_sha256':witness['identity_hmac_sha256']}
  attached={'binding':binding,'commands':{},'review_setup_authority':{'identity':identity,'launches_used':0,'owner_comment_id':123,'owner_comment_sha256':'a'*64,'authorization_identity_sha256':self.auth.identity_sha256}}
  state={'repository':'example/repo','issue_number':1,'task_id':'GH-1','phase':'VERIFIED','capsule_evidence':attached}
  return task,args,state,paths,bundle,manifest,witness
 def command(self,task,args,state,preflight,receipt):
  with mock.patch.object(task,'revalidate_review_setup_owner'),mock.patch.object(task,'load_state',return_value=state),mock.patch.object(task,'git',return_value=self.candidate),mock.patch.object(task,'resolve_repo_root',side_effect=lambda p:p),mock.patch.object(task,'repository_slug',return_value='example/repo'),mock.patch.object(task,'require_trusted_main_controller',return_value=self.base),mock.patch.object(task,'resolve_current_authorization',return_value=self.auth),mock.patch.object(task,'revalidate_attached_governing_issue'),mock.patch.object(task.candidate_evidence,'revalidate_manual'),mock.patch.object(task.candidate_evidence,'evidence_packet',return_value={'synthetic':True}),mock.patch.object(task.candidate_evidence,'create_key',return_value=b'k'*32),mock.patch.object(task,'emit'),mock.patch.object(review,'preflight_model',return_value=preflight) as catalog,mock.patch.object(review,'run_review',return_value=receipt) as run:
   result=task.command_evidence(args)
  return result,catalog,run
 def test_public_cli_preflight_and_review_forward_authenticated_inputs(self):
  task,args,state,paths,bundle,manifest,witness=self.setup();identity=state['capsule_evidence']['review_setup_authority']['identity'];selected={'runtime':identity['runtime'],'model':args.model,'effort':args.effort}
  _,catalog,run=self.command(task,args,state,selected,{})
  catalog.assert_called_once();run.assert_not_called();self.assertEqual(state['capsule_evidence']['review_preflight']['setup_identity'],identity)
  self.assertEqual(state['capsule_evidence']['review_setup_authority']['launches_used'],0)
  args.action='review';receipt={'verdict':{'disposition':'bounded-correction','summary':'Synthetic CLI fixture'},'session':{'thread_id':'synthetic'}}
  _,catalog,run=self.command(task,args,state,selected,receipt)
  catalog.assert_not_called();run.assert_called_once();kwargs=run.call_args.kwargs
  self.assertEqual(kwargs['workflow_instructions'],bundle);self.assertEqual(kwargs['workflow_manifest'],manifest);self.assertEqual(kwargs['expected_account_route'],witness['route']);self.assertEqual(kwargs['expected_account_witness'],witness)
  self.assertEqual(kwargs['expected_runtime_identity'],identity['runtime']);self.assertEqual(state['capsule_evidence']['review_setup_authority']['launches_used'],1)
  with self.assertRaisesRegex(evidence.EvidenceError,'CONSUMED'):task.resolve_review_setup(args,state['capsule_evidence'],state['capsule_evidence']['binding'],self.candidate)
 def test_missing_partial_anonymous_changed_consumed_and_wrong_epoch_fail(self):
  task,args,state,paths,*_=self.setup();attached=state['capsule_evidence'];binding=attached['binding']
  for field in ('workflow_manifest','account_route_approval','account_readiness','owner_authority_provenance'):
   bad=copy.copy(args);setattr(bad,field,None)
   with self.assertRaisesRegex(evidence.EvidenceError,'COMPLETE_INPUTS'):task.resolve_review_setup(bad,attached,binding,self.candidate)
  for mutate in (lambda x:x.pop('review_setup_authority'),lambda x:x['review_setup_authority'].update(launches_used=1),lambda x:x['review_setup_authority']['identity'].update(candidate_sha='0'*40),lambda x:x.update(pre_review_failures=[{}])):
   bad=copy.deepcopy(attached);mutate(bad)
   with self.assertRaisesRegex(evidence.EvidenceError,'CONTROLLER_AUTHORITY'):task.resolve_review_setup(args,bad,binding,self.candidate)
  paths['manifest'].write_text(paths['manifest'].read_text()+' ')
  with self.assertRaisesRegex(evidence.EvidenceError,'CONTROLLER_AUTHORITY'):task.resolve_review_setup(args,attached,binding,self.candidate)
 def test_wrong_route_runtime_readiness_and_digest_rejected_before_dispatch(self):
  task,args,state,paths,*_=self.setup();attached=state['capsule_evidence'];original=paths['approval'].read_text()
  for field in ('route','runtime','readiness_sha256','account_identity_hmac_sha256'):
   bad=json.loads(original)
   if field=='route':bad[field]['backendOrigin']='https://invalid.example'
   elif field=='runtime':bad[field]['sha256']='0'*64
   else:bad[field]='0'*64
   paths['approval'].write_text(json.dumps(bad))
   with self.assertRaises(evidence.EvidenceError):task.resolve_review_setup(args,attached,attached['binding'],self.candidate)
  paths['approval'].write_text(original)
  bad=json.loads(paths['manifest'].read_text());bad[next(iter(bad))]='0'*64;paths['manifest'].write_text(json.dumps(bad))
  with self.assertRaisesRegex(evidence.EvidenceError,'DIGEST'):task.resolve_review_setup(args,attached,attached['binding'],self.candidate)
 def test_setup_preflight_staleness_and_legacy_no_flags(self):
  task,args,state,*_=self.setup();attached=state['capsule_evidence'];identity,kwargs=task.resolve_review_setup(args,attached,attached['binding'],self.candidate)
  attached['review_preflight']={**identity,'setup_identity':identity}
  with self.assertRaisesRegex(evidence.EvidenceError,'SETUP_NOT_PREFLIGHTED'):task.require_review_preflight(attached,attached['binding'],self.candidate,setup_identity={**identity,'route':{}})
  unsupported=copy.copy(args);unsupported.runtime_version=review.QUALIFIED_VERSION
  with self.assertRaisesRegex(evidence.EvidenceError,'ACCOUNT_RUNTIME_UNSUPPORTED'):task.resolve_review_setup(unsupported,attached,attached['binding'],self.candidate)
  legacy=task.build_parser().parse_args(['evidence','1','preflight','--candidate-root',str(self.repo)])
  self.assertEqual(task.resolve_review_setup(legacy,{},attached['binding'],self.candidate),({},{}))
 def test_live_account_identity_gate_precedes_thread(self):
  # Actual helper's new interface rejects malformed expected metadata before Popen.
  binding=self.binding();identity={'executable':str(Path(sys.executable).resolve()),'sha256':'a'*64,'version':'codex-cli 0.159.2'}
  with mock.patch.object(review,'runtime',return_value=identity),mock.patch.object(review.subprocess,'Popen') as process:
   with self.assertRaisesRegex(evidence.EvidenceError,'READINESS_INVALID'):review.run_review(self.repo,binding,{},directory=self.root/'never',executable=Path(sys.executable),expected_sha256='a'*64,key=b'k'*32,expected_runtime_version='codex-cli 0.159.2',expected_account_route={'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'},expected_account_witness={'private':'must reject'})
   process.assert_not_called()
