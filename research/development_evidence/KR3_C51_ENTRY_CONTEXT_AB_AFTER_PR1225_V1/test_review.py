"""Post-outcome saved-evidence regressions; not economic trials."""
from copy import deepcopy
import unittest
from pathlib import Path
import verify_review as r

class ReviewChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=r.s.HERE;cls.v=r.s.load_checker(cls.root.parents[2])
        cls.parents={p:r.s.gz(cls.root.parents[2]/r.s.PARENT/p/'RESULT.json.gz') for p in r.s.PERIODS}
        cls.children={p:r.s.gz(cls.root/'B'/p/'RESULT.json.gz') for p in r.s.PERIODS}
        cls.derived={p:r.derive(cls.parents[p],cls.children[p],cls.v) for p in r.s.PERIODS}
        cls.text=(cls.root/'INTERPRETATION.md').read_text()
    def test_full(self):self.assertTrue(r.verify()['interpretation_recomputed'])
    def test_every_numeric_field_recomputed(self):
        def numbers(obj,path=()):
            if isinstance(obj,dict):
                for k,v in obj.items():yield from numbers(v,path+(k,))
            elif isinstance(obj,(int,float)) and not isinstance(obj,bool):yield path
        for path in numbers(self.derived):
            changed=deepcopy(self.derived);target=changed
            for part in path[:-1]:target=target[part]
            target[path[-1]]+=10
            with self.subTest(path=path),self.assertRaises(ValueError):r.check_derived(changed,self.derived,self.v)
    def test_markdown_numbers_not_just_hashes(self):
        for old,new in [('13666.60','13667.60'),('96.66%','99.99%'),('884.35','885.35'),('completed losses+2284.72','completed losses+2285.72'),('−118.28bps','+118.28bps')]:
            changed=self.text.replace(old,new);self.assertNotEqual(changed,self.text)
            with self.subTest(old=old),self.assertRaisesRegex(ValueError,'MARKDOWN'):r.markdown_checks(changed,self.parents,self.children,self.derived,self.v)
    def test_narrow_workflow_would_fail(self):
        spec=r.s.read(self.root/'SPEC.json')
        with self.assertRaisesRegex(ValueError,'UNTRIGGERED_DEPENDENCY'):r.coverage("  - 'backend/research/rebuild/*c51_entry_context*.py'",spec)
    def test_winner_or_loss_sign_changes_are_visible(self):
        child=deepcopy(self.children['DEV2025']);child['trades'][0]['net_bps']=-child['trades'][0]['net_bps']
        d=r.derive(self.parents['DEV2025'],child,self.v)
        with self.assertRaises(ValueError):self.v.same(d,self.derived['DEV2025'],'DERIVED')
    def test_fixed_comparison_has_no_replay_import(self):
        source=Path(r.__file__).read_text()
        self.assertNotIn('from backend',source);self.assertNotIn('import requests',source)
if __name__=='__main__':unittest.main()
