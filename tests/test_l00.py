"""L00的第一条红色验收；不要删除测试或把NotImplementedError算通过。"""
import unittest
from devagent.app import run_task

class TestL00StartingContract(unittest.TestCase):
    def test_empty_input_never_calls_client(self):
        class NeverCall:
            def complete(self, request):
                raise AssertionError('invalid input must not call model')
        result=run_task('  ',NeverCall())
        self.assertEqual(result.status,'failed')
        self.assertEqual(result.error_code,'invalid_input')
        self.assertEqual(result.exit_code,2)
