import io,json,os,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from backend.research.architecture_factory.a1_manual_research_budget_v1 import ManualRequestBudget
from backend.research.architecture_factory import a1_youtube_diversity_scout_v1 as s

CONTEXT=dict(blocker='FADING_REENTRY',lane=['primary'],candidate='frozen_parent',failure_signature='loss_cluster_and_dropped_winners',required_sources=['DMI'],development_evidence_ref='dev/receipt.json',implementation_sha256='a'*64,buckets=['trend'])
def response(value):return io.BytesIO(json.dumps(value).encode())
def generated(value):return {'candidates':[{'content':{'parts':[{'text':json.dumps(value)}]}}],'usageMetadata':{'promptTokenCount':12,'candidatesTokenCount':20},'modelVersion':'test-fixed'}
class Requests(unittest.TestCase):
    def test_actual_search_and_video_body_carry_failure_context(self):
        captured=[]
        def transport(req,**kw):
            if req.data is None:return response({'models':[{'name':'models/test','supportedGenerationMethods':['generateContent']}]})
            captured.append(json.loads(req.data));return response(generated({'status':'USE'}))
        b=ManualRequestBudget()
        with patch('urllib.request.urlopen',transport):
            s.call_gemini_search('test',['models/test'],s._search_prompt([('trend','strength')],CONTEXT),9999,request_budget=b)
            s.call_gemini_video('test',['models/test'],s._video_prompt({'url':'https://www.youtube.com/watch?v=exact','video_id':'exact'},CONTEXT),'https://www.youtube.com/watch?v=exact',9999,request_budget=b)
        for req in captured:
            prompt=req['contents'][0]['parts'][0]['text']
            for k in ['FADING_REENTRY','frozen_parent','loss_cluster_and_dropped_winners','dev/receipt.json','a'*64]:self.assertIn(k,prompt)
            self.assertEqual(req['generationConfig']['maxOutputTokens'],3500)
        part=captured[1]['contents'][0]['parts'][1]
        self.assertEqual(part['file_data']['file_uri'],'https://www.youtube.com/watch?v=exact')
        self.assertEqual(part['videoMetadata']['endOffset'],'600s')
        self.assertEqual(b.receipt()['generation_requests'],2)
        self.assertEqual(len(b.requests),3) # catalog only once
        self.assertIsNone(b.receipt()['cost_usd'])
        self.assertTrue(all('test' not in str(x.get('request_body',{}).get('headers',{})) for x in b.requests))

    def test_failed_actual_attempt_consumes_budget_without_fallback(self):
        b=ManualRequestBudget(max_search=1,max_video=1);b.available=['models/test','models/fallback']
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('u',500,'fail',{},None)) as call:
            for _ in range(2):
                with self.assertRaises(RuntimeError):s.call_gemini_search('test',['models/test','models/fallback'],'x',100,request_budget=b)
            self.assertEqual(call.call_count,1)
        self.assertEqual(b.receipt()['generation_requests'],1)
        self.assertEqual(b.requests[0]['status'],'FAILED')
        self.assertEqual(b.receipt()['fallbacks'],0)

    def test_context_related_scope_and_holdout_reference(self):
        for ctx in [{},{**CONTEXT,'buckets':['funding']},{**CONTEXT,'development_evidence_ref':'Break_validation/receipt'}]:
            with self.assertRaises(ValueError):s.validate_context(ctx)
        self.assertFalse(s._verified_registry({'sources':[{'url':'https://youtu.be/a','observed_views':999}]})['https://www.youtube.com/watch?v=a']['view_count_verified'])
        candidate={'video_id':'a','url':'https://youtu.be/a'}
        source=s._accepted_source(candidate,{'analysis_mode':'TRANSCRIPT_ONLY','analyzed_video_id':'a'},'test')
        self.assertFalse(source['direct_video_analysis'])
        self.assertEqual(s._priority([candidate],[],{'a':{'status':'FAILED_NO_AUTO_RETRY'}}),[])

    def test_scoped_failure_cache_stops_repeated_requests(self):
        pool={'candidate_pool':[{'video_id':'a','url':'https://youtu.be/a','bucket':'trend'}]}
        with tempfile.TemporaryDirectory() as tmp:
            existing=Path(tmp)/'existing.json';out=Path(tmp)/'receipt.json';existing.write_text(json.dumps(pool))
            with patch.dict(os.environ,{'GEMINI_API_KEY':'test'}),patch.object(s,'call_gemini_search',side_effect=RuntimeError('FAILED')) as search,patch.object(s,'call_gemini_video',side_effect=RuntimeError('FAILED')) as video:
                first=s.run(out,existing,context=CONTEXT)
                self.assertEqual(search.call_count,1);self.assertEqual(video.call_count,1)
                s.run(out,out,context=CONTEXT)
                self.assertEqual(search.call_count,1);self.assertEqual(video.call_count,1)
            self.assertEqual(set(first['buckets']),{'trend'})
            self.assertFalse(first['sealed_holdout_outcomes_exposed'])
            self.assertFalse(first['selection_authority'])

    def test_prompt_cap_prevents_transport(self):
        b=ManualRequestBudget();b.available=['models/test']
        with patch('urllib.request.urlopen') as call:
            with self.assertRaises(RuntimeError):s.call_gemini_video('test',['models/test'],'x'*18001,'https://youtu.be/a',100,request_budget=b)
            call.assert_not_called()
        self.assertEqual(b.receipt()['generation_requests'],0)

if __name__=='__main__':unittest.main()
