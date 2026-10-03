from pathlib import Path
import sys,json,copy,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib import independent_review as review
from lib.candidate_evidence import EvidenceError
class AccountEventAdapterTests(unittest.TestCase):
 def account(self,identity='synthetic-account-A',origin='https://chatgpt.com',routing='NO_CONSTRAINT'):
  return {'requiresOpenaiAuth':True,'account':{'type':'chatgpt','email':'synthetic@example.invalid','planType':'prolite'},'workspaceRouting':{'chatgptAccountId':identity,'backendOrigin':origin,'accountRoutingOverride':routing}}
 def context(self):
  witness=review.account_witness(self.account(),b'k'*32,{'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'})
  return {'runtime_version':'codex-cli 0.159.2','model':'gpt-6.1-sol','effort':'low','initial':witness,'final':copy.deepcopy(witness),'initial_read_id':10,'final_read_id':11}
 def trace(self):
  witness=self.context()['initial']
  return [{'direction':'received','message':{'method':'account/updated','params':{'authMode':'chatgpt','planType':'prolite'},'emittedAtMs':1}},
          {'direction':'sent','message':{'id':10,'method':'account/read','params':{'refreshToken':False}}},
          {'direction':'received','message':{'id':10,'result':copy.deepcopy(witness)}},
          {'direction':'sent','message':{'method':'thread/start','params':{'model':'gpt-6.1-sol','config':{'model_reasoning_effort':'low'}}}},
          {'direction':'received','message':{'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}}},
          {'direction':'sent','message':{'id':11,'method':'account/read','params':{'refreshToken':False}}},
          {'direction':'received','message':{'id':11,'result':copy.deepcopy(witness)}}]
 def test_safe_prethread_snapshot_with_identity_witness(self):
  review.validate_trace(self.trace(),'thread','turn',runtime_version='codex-cli 0.159.2',account_context=self.context())
 def test_old_retained_trace_cannot_gain_missing_account_proof(self):
  fixture=Path(__file__).resolve().parent/'fixtures/account-event-without-proof.json'
  retained=json.loads(fixture.read_text());trace=retained['trace']
  for version in ('codex-cli 0.153.4','codex-cli 0.159.2'):
   with self.assertRaises(EvidenceError):review.validate_trace(trace,retained['thread_id'],retained['turn_id'],runtime_version=version)
 def test_unknown_malformed_null_mode_plan_and_late_repeated_events_fail(self):
  for params in ({'authMode':None,'planType':None},{'authMode':'unknown','planType':'prolite'},{'authMode':'chatgpt','planType':'unknown'},{'authMode':'chatgpt','planType':None},{'authMode':'chatgpt','planType':'prolite','other':'unexpected'},{'authMode':'apikey','planType':'prolite'},{'planType':'prolite'}):
   trace=self.trace();trace[0]['message']['params']=params
   with self.assertRaises(EvidenceError):review.validate_trace(trace,'thread','turn',runtime_version='codex-cli 0.159.2',account_context=self.context())
  for trace in ([self.trace()[3],self.trace()[0]],[self.trace()[0],self.trace()[0],*self.trace()[1:]]):
   with self.assertRaises(EvidenceError):review.validate_trace(trace,'thread','turn',runtime_version='codex-cli 0.159.2',account_context=self.context())
 def test_same_mode_plan_identity_and_route_transition_fail(self):
  context=self.context()
  for account in (self.account(identity='synthetic-account-B'),self.account(origin='https://evil.invalid'),self.account(routing='us')):
   with self.assertRaises(EvidenceError):
    context['final']=review.account_witness(account,b'k'*32,{'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'})
    review.validate_trace(self.trace(),'thread','turn',runtime_version='codex-cli 0.159.2',account_context=context)
 def test_malformed_account_missing_id_unknown_shape_and_null_email_fail(self):
  for mutate in (lambda x:x['workspaceRouting'].pop('chatgptAccountId'),lambda x:x.update(extra=True),lambda x:x.update(account=None),lambda x:x['account'].update(email=None),lambda x:x['workspaceRouting'].update(backendOrigin='https://evil.invalid'),lambda x:x.update(requiresOpenaiAuth=False)):
   data=self.account();mutate(data)
   with self.assertRaises(EvidenceError):review.account_witness(data,b'k'*32,{'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'})
 def test_legacy_unknown_runtime_and_model_effort_context_fail(self):
  for version in ('codex-cli 0.153.4','codex-cli 9.9.9'):
   with self.assertRaises(EvidenceError):review.validate_trace(self.trace(),'thread','turn',runtime_version=version,account_context=self.context())
  for field,value in [('model','substitute'),('effort','high')]:
   c=self.context();c[field]=value
   with self.assertRaises(EvidenceError):review.validate_trace(self.trace(),'thread','turn',runtime_version='codex-cli 0.159.2',account_context=c)
 def test_witness_contains_no_private_fields_and_no_token_acceptance(self):
  witness=self.context()['initial'];text=json.dumps(witness)
  self.assertNotIn('synthetic-account-A',text);self.assertNotIn('synthetic@example.invalid',text)
  bad=self.account();bad['account']['token']='not-a-real-credential'
  with self.assertRaises(EvidenceError):review.account_witness(bad,b'k'*32,{'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'})
 def test_account_read_trace_redaction_success_and_malformed(self):
  from unittest import mock
  route={'backendOrigin':'https://chatgpt.com','accountRoutingOverride':'NO_CONSTRAINT'}
  for raw,valid in [(self.account(),True),({**self.account(),'token':'synthetic-never-hash'},False)]:
   rpc=mock.Mock();rpc.next_id=42;rpc.trace=[{'direction':'received','message':{'id':42,'result':raw}}];rpc.request.return_value=raw
   if valid:
    witness,identifier=review.read_account_witness(rpc,b'k'*32,route)
    self.assertEqual(identifier,42);self.assertEqual(rpc.trace[0]['message']['result'],witness)
   else:
    with self.assertRaises(EvidenceError):review.read_account_witness(rpc,b'k'*32,route)
   text=json.dumps(rpc.trace)
   self.assertNotIn('synthetic-account-A',text);self.assertNotIn('synthetic@example.invalid',text);self.assertNotIn('synthetic-never-hash',text)
   rpc.request.assert_called_once_with('account/read',{'refreshToken':False})
 def test_missing_or_unauthenticated_account_reads_fail(self):
  context=self.context();trace=self.trace()
  for bad in (trace[:1]+trace[3:],trace[:-2],trace[:]):
   if bad==trace:bad[1]['message']['params']={'refreshToken':True}
   with self.assertRaises(EvidenceError):review.validate_trace(bad,'thread','turn',runtime_version='codex-cli 0.159.2',account_context=context)
