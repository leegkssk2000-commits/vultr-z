"""Mock actual reviewed run/request plumbing; no remote or paid requests."""
import unittest
from unittest.mock import patch
from backend.research.benchmark import creator_squeeze_reviewed_v1 as r

class TransportTests(unittest.TestCase):
 def observe(self,url,**kw):
  before=(r.a.authorize,r.a.decode,r.a.make_prompt,r.a.Request)
  def request_from_run():return r.a.request(url,**kw)
  with patch.object(r.a,'run',side_effect=request_from_run),patch.object(r.a,'build_opener') as build:
   response=build.return_value.open.return_value.__enter__.return_value
   response.read.return_value=b'{}';response.status=200
   r.run()
   build.return_value.open.assert_called_once()
   req=build.return_value.open.call_args.args[0]
   self.assertEqual(build.return_value.open.call_args.kwargs['timeout'],kw.get('timeout',60))
   self.assertIsInstance(build.call_args.args[0],r.a.NoRedirect)
  self.assertEqual(before,(r.a.authorize,r.a.decode,r.a.make_prompt,r.a.Request))
  return req
 def test_actual_initial_GitHub_GET(self):
  q=self.observe('https://api.github.com/repos/o/r/pulls/1235',key='TEST',timeout=20)
  self.assertEqual(q.get_header('Accept'),'application/vnd.github+json')
  self.assertEqual(q.get_header('Authorization'),'Bearer TEST');self.assertEqual(q.get_method(),'GET');self.assertIsNone(q.data)
 def test_atomic_claim_POST(self):
  body={'ref':'refs/heads/test','sha':'a'*40}
  q=self.observe('https://api.github.com/repos/o/r/git/refs',key='TEST',body=body)
  self.assertEqual(q.get_header('Accept'),'application/vnd.github+json');self.assertEqual(q.data,r.a.canonical(body));self.assertEqual(q.get_method(),'POST')
 def test_public_HTML_without_credentials(self):
  q=self.observe('https://www.simplertrading.com/join/futures/john-carter')
  self.assertEqual(q.get_header('Accept'),'text/html');self.assertIsNone(q.get_header('Authorization'))
 def test_gemini_unchanged(self):
  body={'contents':[],'tools':[]};q=self.observe('https://generativelanguage.googleapis.com/v1beta/models/test:generateContent',body=body,key='TEST',provider='gemini')
  self.assertEqual(q.get_header('Accept'),'application/json');self.assertEqual(q.get_header('X-goog-api-key'),'TEST');self.assertIsNone(q.get_header('Authorization'));self.assertEqual(q.data,r.a.canonical(body))
 def test_openai_unchanged(self):
  body={'input':'TEST','store':False};q=self.observe('https://api.openai.com/v1/responses',body=body,key='TEST',provider='openai')
  self.assertEqual(q.get_header('Accept'),'application/json');self.assertEqual(q.get_header('Authorization'),'Bearer TEST');self.assertEqual(q.data,r.a.canonical(body))
 def test_host_suffix_not_GitHub(self):
  q=self.observe('https://api.github.com.example.invalid/path');self.assertEqual(q.get_header('Accept'),'text/html')
 def test_path_not_host(self):
  q=self.observe('https://example.invalid/api.github.com');self.assertEqual(q.get_header('Accept'),'text/html')
 def test_exception_restores_every_hook(self):
  before=(r.a.authorize,r.a.decode,r.a.make_prompt,r.a.Request)
  with patch.object(r.a,'run',side_effect=RuntimeError('injected')):
   with self.assertRaisesRegex(RuntimeError,'injected'):r.run()
  self.assertEqual(before,(r.a.authorize,r.a.decode,r.a.make_prompt,r.a.Request))
 def test_redirect_remains_forbidden(self):
  with self.assertRaisesRegex(ValueError,'REDIRECT_NOT_AUTHORIZED'):r.a.NoRedirect().redirect_request(None)
 def test_response_size_still_bounded(self):
  def request_from_run():r.a.request('https://api.github.com/repos/o/r/pulls/1235')
  with patch.object(r.a,'run',side_effect=request_from_run),patch.object(r.a,'build_opener') as build:
   build.return_value.open.return_value.__enter__.return_value.read.return_value=b'x'*2000001
   with self.assertRaisesRegex(ValueError,'RESPONSE_LIMIT'):r.run()
if __name__=='__main__':unittest.main()
