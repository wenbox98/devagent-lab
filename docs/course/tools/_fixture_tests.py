"""由grade_fixture调用的公共参考测试。只执行自有受控练习代码，不是安全沙箱。"""
import importlib.util
import json
from pathlib import Path
import random
import sys
import unittest

path=Path(sys.argv[1]).resolve()/'pagination.py'
spec=importlib.util.spec_from_file_location('candidate_pagination',path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TestPagination(unittest.TestCase):
    def test_first(self): self.assertEqual(m.page([1,2,3],1,2),[1,2])
    def test_second(self): self.assertEqual(m.page([1,2,3,4],2,2),[3,4])
    def test_last(self): self.assertEqual(m.page([1,2,3],2,2),[3])
    def test_empty(self): self.assertEqual(m.page([],1,2),[])
    def test_outside(self): self.assertEqual(m.page([1,2],4,2),[])
    def test_invalid_page(self):
        for x in [0,-1,True,1.5]:
            with self.subTest(x=x),self.assertRaises(ValueError):m.page([1],x,1)
    def test_invalid_size(self):
        for x in [0,-1,False,2.5]:
            with self.subTest(x=x),self.assertRaises(ValueError):m.page([1],1,x)
    def test_input_unchanged(self):
        x=[1,2,3];copy=x[:];m.page(x,1,2);self.assertEqual(x,copy)
    def test_generated_public_cases(self):
        rng=random.Random(9187)
        for _ in range(30):
            x=list(range(rng.randrange(0,30)));p=rng.randrange(1,10);size=rng.randrange(1,8)
            with self.subTest(length=len(x),page=p,size=size):
                self.assertEqual(m.page(x,p,size),x[(p-1)*size:p*size])

suite=unittest.defaultTestLoader.loadTestsFromTestCase(TestPagination)
r=unittest.TextTestRunner(stream=sys.stderr,verbosity=1).run(suite)
print(json.dumps({'collected':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped)}))
raise SystemExit(0 if r.wasSuccessful() and r.testsRun>0 else 1)
