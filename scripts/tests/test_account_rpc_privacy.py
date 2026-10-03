from pathlib import Path
import sys,json,copy,time
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib import independent_review as r,candidate_evidence as e
from test_candidate_evidence import CandidateFixture
ACCOUNT={'requiresOpenaiAuth':True,'account':{'type':'chatgpt','email':'synthetic@example.invalid','planType':'prolite'},'workspaceRouting':{'chatgptAccountId':'synthetic-account-A','backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'}}
ROUTE={'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'}
class AccountRpcPrivacyTests(CandidateFixture):
 def rpc(self,frame,pending=True):
  rpc=object.__new__(r.Rpc);rpc.trace=[];rpc.account_privacy_enabled=True
  rpc.account_reads={42:{'key':b'k'*32,'route':ROUTE,'witness':None,'consumed':False}}
  rpc.pending_request={'id':42,'method':'account/read'} if pending else None
  rpc.buffer=(json.dumps(frame)+'\n').encode();rpc.deadline=time.monotonic()+1
  return rpc
 def assert_private_absent(self,trace):
  text=json.dumps(trace)
  for value in ('synthetic@example.invalid','synthetic-account-A','synthetic-secret-marker','synthetic-credential-marker'):self.assertNotIn(value,text)
 def test_actual_read_ingress_unknown_field_wrong_id_error_and_malformed_redact_and_reject(self):
  frames=[{'id':42,'result':copy.deepcopy(ACCOUNT),'unexpectedPrivateField':'synthetic-secret-marker'},
          {'id':43,'result':copy.deepcopy(ACCOUNT)},
          {'id':42,'error':{'message':'synthetic@example.invalid','data':'synthetic-credential-marker'}},
          {'id':42,'result':copy.deepcopy(ACCOUNT),'error':'synthetic-secret-marker'},
          {'id':None,'result':copy.deepcopy(ACCOUNT)},
          {'id':{},'result':copy.deepcopy(ACCOUNT)},
          {'unexpectedPrivateField':'synthetic-secret-marker'},
          ['synthetic-secret-marker'],
          {'id':42,'result':{**copy.deepcopy(ACCOUNT),'token':'synthetic-credential-marker'}}]
  for frame in frames:
   rpc=self.rpc(frame)
   with self.assertRaises(e.EvidenceError):rpc.read()
   self.assert_private_absent(rpc.trace)
   self.assertEqual(len(rpc.trace),1)
 def test_actual_read_ingress_valid_witness_provenance(self):
  rpc=self.rpc({'id':42,'result':copy.deepcopy(ACCOUNT),'emittedAtMs':1});result=rpc.read()
  self.assertEqual(result['id'],42);self.assertEqual(result['emittedAtMs'],1)
  self.assertEqual(result['result'],rpc.account_reads[42]['witness']);self.assertTrue(rpc.account_reads[42]['consumed'])
  self.assert_private_absent(rpc.trace)
 def test_actual_terminal_drain_late_or_wrong_response_is_redacted(self):
  for identifier in (42,43):
   rpc=self.rpc({'id':identifier,'result':copy.deepcopy(ACCOUNT)},pending=False)
   rpc.process=mock.Mock();rpc.process.pid=987654321;rpc.selector=mock.Mock();rpc.selector.select.return_value=True
   with mock.patch.object(r.os,'killpg'),mock.patch.object(r.os,'read',return_value=b''):
    with self.assertRaises(e.EvidenceError):rpc.close()
   self.assert_private_absent(rpc.trace)
 def test_defensive_custom_transport_exact_review_reproductions(self):
  for frame in ({'id':42,'result':copy.deepcopy(ACCOUNT),'unexpectedPrivateField':'synthetic-secret-marker'}, {'id':43,'result':copy.deepcopy(ACCOUNT)}):
   rpc=mock.Mock();rpc.next_id=42;rpc.trace=[{'direction':'received','message':frame}];rpc.request.return_value=copy.deepcopy(ACCOUNT)
   with self.assertRaises(e.EvidenceError):r.read_account_witness(rpc,b'k'*32,ROUTE)
   self.assert_private_absent(rpc.trace)
 def flow(self,variant=None):
  binding=self.binding();verdict=self.verdict(binding);captured=[]
  class FakeRpc(r.Rpc):
   def __init__(self):
    self.next_id=1;self.trace=[];self.account_reads={};self.pending_request=None;self.account_privacy_enabled=True;self.accounts=0;self.queue=[]
   def send(self,message):
    self.trace.append({'direction':'sent','message':message});method=message.get('method')
    if 'id' not in message:return
    identifier=message['id'];captured.append((method,message['params']))
    if method=='initialize':
     self.queue.append({'method':'account/updated','params':{'authMode':'chatgpt','planType':'prolite'}});result={}
    elif method=='account/read':
     self.accounts+=1;result=copy.deepcopy(ACCOUNT)
     if variant=='changed' and self.accounts==2:result['workspaceRouting']['chatgptAccountId']='synthetic-account-B'
    elif method=='mcpServerStatus/list':result={'data':[],'nextCursor':None}
    elif method=='thread/start':result={'thread':{'id':'fresh','turns':[],'ephemeral':True},'instructionSources':[],'runtimeWorkspaceRoots':[],'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False},'model':'gpt-6.1-sol','reasoningEffort':'low','modelProvider':'openai'}
    elif method=='turn/start':result={'turn':{'id':'turn'}}
    else:raise AssertionError(method)
    response={'id':identifier,'result':result}
    if method=='account/read' and variant=='wrong-id':response['id']=identifier+100
    if method=='account/read' and variant=='extra':response['unexpectedPrivateField']='synthetic-secret-marker'
    self.queue.append(response)
    if method=='turn/start':self.queue.extend([{'method':'item/completed','params':{'threadId':'fresh','turnId':'turn','item':{'type':'agentMessage','text':json.dumps(verdict)}}},{'method':'turn/completed','params':{'threadId':'fresh','turn':{'id':'turn','status':'completed'}}}])
   def read(self):return self.record_received(self.queue.pop(0))
   def close(self):
    for message in self.queue:self.record_received(message)
    self.queue=[]
  rpc=FakeRpc();identity={'executable':str(Path(sys.executable).resolve()),'sha256':'fixture','version':r.ACCOUNT_EVENT_VERSION};directory=self.root/'review'
  original=r.subprocess.Popen
  def popen(command,*args,**kwargs):return original(command,*args,**kwargs) if command[0]=='git' else mock.Mock()
  with mock.patch.object(r,'runtime',return_value=identity),mock.patch.object(r.subprocess,'Popen',side_effect=popen),mock.patch.object(r,'Rpc',return_value=rpc):
   kwargs=dict(directory=directory,executable=Path(sys.executable),expected_sha256='fixture',key=b'k'*32,model='gpt-6.1-sol',effort='low',expected_runtime_version=r.ACCOUNT_EVENT_VERSION,expected_account_route=ROUTE,expected_account_witness=r.account_witness(ACCOUNT,b'k'*32,ROUTE))
   if variant=='owner-mismatch':kwargs['expected_account_witness']['identity_hmac_sha256']='0'*64
   if variant:
    with self.assertRaisesRegex(e.EvidenceError,'INDEPENDENT_REVIEW_STOP_REPLAN'):r.run_review(self.repo,binding,{},**kwargs)
    self.assertFalse((directory/'receipt.json').exists());self.assertFalse((directory/'report.json').exists())
   else:
    receipt=r.run_review(self.repo,binding,{},**kwargs);imported=json.loads((directory/'receipt.json').read_text());e.authenticate_receipt(imported,b'k'*32,binding)
    self.assertEqual(json.loads((directory/'report.json').read_text()),verdict);self.assertEqual(receipt['report'],e.artifact(directory/'report.json'))
    self.assertEqual([p for m,p in captured if m=='account/read'],[{'refreshToken':False}]*2)
    self.assertEqual(receipt['session']['account_context']['initial'],receipt['session']['account_context']['final'])
   if variant=='owner-mismatch':self.assertNotIn('thread/start',[m for m,p in captured])
   self.assert_private_absent(json.loads((directory/'trace.json').read_text()))
 def test_full_mocked_159_review_two_reads_provider_receipt_and_report_import(self):self.flow()
 def test_full_mocked_159_changed_account_fail_closed(self):self.flow('changed')
 def test_owner_bound_readiness_mismatch_stops_before_thread(self):self.flow('owner-mismatch')
 def test_full_mocked_159_wrong_id_failure_no_private_trace_or_receipt(self):self.flow('wrong-id')
 def test_full_mocked_159_unknown_envelope_failure_no_private_trace_or_receipt(self):self.flow('extra')

 def test_misrouted_account_payload_in_other_rpc_wait_is_not_retained(self):
  rpc=self.rpc({'id':77,'result':copy.deepcopy(ACCOUNT)})
  rpc.pending_request={'id':77,'method':'mcpServerStatus/list'}
  with self.assertRaises(e.EvidenceError):rpc.read()
  self.assert_private_absent(rpc.trace)
 def test_unknown_envelope_and_token_fields_are_never_hashed(self):
  for frame in ({'id':42,'result':copy.deepcopy(ACCOUNT),'unexpected':'synthetic-secret-marker'}, {'id':42,'result':{**copy.deepcopy(ACCOUNT),'token':'synthetic-credential-marker'}}):
   rpc=self.rpc(frame)
   with mock.patch.object(r.hmac,'new',side_effect=AssertionError('unknown credential must never be hashed')):
    with self.assertRaises(e.EvidenceError):rpc.read()
   self.assert_private_absent(rpc.trace)
