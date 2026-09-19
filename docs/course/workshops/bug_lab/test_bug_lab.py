import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('course_student', Path(__file__).with_name('student.py'))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

class TestL00(unittest.TestCase):
    def test_integer_task_is_rejected_before_client(self):
        calls = []
        self.assertEqual(s.handle(42, lambda x: calls.append(x) or 'ok'), 'invalid_input')
        self.assertEqual(calls, [])
    def test_blank_does_not_call(self):
        calls = []
        self.assertEqual(s.handle('   ', lambda x: calls.append(x) or 'ok'), 'invalid_input')
        self.assertEqual(calls, [])
    def test_success_uses_clean_input(self):
        calls = []
        self.assertEqual(s.handle(' fix ', lambda x: calls.append(x) or 'ok'), 'succeeded')
        self.assertEqual(calls, ['fix'])
    def test_timeout_is_separate(self):
        def timeout(x): raise TimeoutError('fixture')
        self.assertEqual(s.handle('fix', timeout), 'model_timeout')
    def test_non_string_response_is_invalid(self):
        self.assertEqual(s.handle('fix', lambda x: 42), 'invalid_response')

class TestL02(unittest.TestCase):
    def test_child_is_allowed(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(s.is_within(Path(t)/'repo', Path(t)/'repo'/'a.py'))
    def test_sibling_is_denied(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(s.is_within(Path(t)/'repo', Path(t)/'repo2'/'a.py'))
    def test_parent_escape_is_denied(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(s.is_within(Path(t)/'repo', Path(t)/'repo'/'..'/'outside.py'))

class TestL07(unittest.TestCase):
    def test_same_base(self): self.assertTrue(s.base_matches('a', 'a'))
    def test_changed_base(self): self.assertFalse(s.base_matches('b', 'a'))
    def test_missing_base(self): self.assertFalse(s.base_matches('', ''))

class TestL10(unittest.TestCase):
    def test_same_scope_reuses_key(self): self.assertEqual(s.operation_key('a','1'),s.operation_key('a','1'))
    def test_tenants_do_not_collide(self): self.assertNotEqual(s.operation_key('a','1'),s.operation_key('b','1'))
    def test_keys_do_not_collide(self): self.assertNotEqual(s.operation_key('a','1'),s.operation_key('a','2'))

class TestL12(unittest.TestCase):
    def report(self, **change):
        r=dict(claim='succeeded',exit_code=0,collected=4,passed=4,snapshot_hash='v2',scope_ok=True)
        r.update(change); return r
    def test_current_pass(self): self.assertTrue(s.verified(self.report(),'v2'))
    def test_zero_tests(self): self.assertFalse(s.verified(self.report(collected=0,passed=0),'v2'))
    def test_old_report(self): self.assertFalse(s.verified(self.report(snapshot_hash='v1'),'v2'))
    def test_wrong_scope(self): self.assertFalse(s.verified(self.report(scope_ok=False),'v2'))
    def test_claim_is_not_the_grader(self): self.assertTrue(s.verified(self.report(claim='failed'),'v2'))

class TestF04(unittest.TestCase):
    def test_delta(self): self.assertEqual(s.evidence_delta({'evidence':['a']},'b'),{'evidence':['b']})
    def test_merge_once(self):
        old=['a']; delta=s.evidence_delta({'evidence':old},'b')
        self.assertEqual(old+delta['evidence'],['a','b']);self.assertEqual(old,['a'])

class TestR01(unittest.TestCase):
    def test_denominator_is_all_relevant(self): self.assertAlmostEqual(s.recall_at_k({'a','b'},['a'],1),0.5)
    def test_duplicate_hit_counts_once(self): self.assertAlmostEqual(s.recall_at_k({'a','b'},['a','a'],2),0.5)
    def test_no_relevance_separate(self): self.assertIsNone(s.recall_at_k(set(),['a'],1))
    def test_miss(self): self.assertEqual(s.recall_at_k({'a'},['b'],1),0.0)

class TestR02(unittest.TestCase):
    def test_duplicate_does_not_vote_twice(self):
        self.assertEqual(s.rrf([['b','b','b'],['a']]),['a','b'])
    def test_stable_tie(self): self.assertEqual(s.rrf([['z'],['a']]),['a','z'])
    def test_empty_backend(self): self.assertEqual(s.rrf([[],['a','b']]),['a','b'])
    def test_negative_constant(self):
        with self.assertRaises(ValueError): s.rrf([['a']],-1)

if __name__=='__main__': unittest.main()
